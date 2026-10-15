---
name: song-mv
description: 给一个歌曲视频链接（YouTube 等），产出 4K + 60帧插帧 + 水印 + 原文/中文双语歌词 + FLAC Hi-Res 的成品视频，以及 B 站投稿用的 16:9 / 4:3 封面和元数据 JSON。当用户给出歌曲链接并要求“做视频 / 出 4K60 / 加双语字幕 / 做封面 / 投稿信息”时使用。
---

# 歌曲 4K60 双语视频流程

一律用 `.venv/bin/python` 运行；人声分离用 `.venv-sep`（make_mv 会自动调用）。安装见 README。

| 入口 | 作用 |
|---|---|
| `pipeline/make_mv.py` | 视频总控：`download → prep → lyrics → separate → align → translate → interp → render`，`--from/--to` 断点续跑 |
| `pipeline/make_cover.py` | 封面：16:9 + 4:3 |
| `pipeline/make_meta.py` | 投稿元数据 JSON |
| `pipeline/get_ytb_lyrics_from_link.py` | YouTube 链接 → Genius 歌词 → `ori_lyrics/<name>.txt`（lyrics 阶段自动调用） |
| `pipeline/eval_subs.py` | 字幕时间轴客观评测，多版本对比 |

产物：每个作品一个目录 `post/X/`：`X 4K60FPS Sub-WaterMark.mp4` + `cover/` + `X.json`；中间文件在 `work/X/`。

## 硬性要求
- **音轨必须是 FLAC 48kHz/24bit**（B 站 “Hi-Res无损” 标）。render 用 `-c:a copy`，渲染后自动检查，不符直接报错
- **字幕文字只来自参考歌词**（YouTube 官方带时间字幕，或 Genius 歌词文本）；识别结果（Qwen）只用来定位、复核，绝不直接上屏
- **Claude 不自己写出或改写歌词、不从网页抓歌词贴进对话**：歌词由 `get_ytb_lyrics_from_link.py` 写进本地文件，或用户自己保存；汇报时只给句号、时间点、统计
- 投稿 JSON 里的事实必须有出处（视频简介、用户提供、可查证资料），生成后人工核对

## 0. 先确认参数
- `--name` 短名；`--lang` 演唱语言（ja / en / es…）；`--title "《歌名》 歌手"`（字幕首行，自动加中文行）
- 视频有**官方人工字幕**（不是自动字幕）→ 加 `--sub-lang ja` 用它作参考，时间轴最准；否则走 Genius 歌词
- 是否截取 `--start/--end`（直播/合集）
- 需要登录：`--cookies-from-browser chrome`（先征得用户同意）。YouTube 常变，先 `.venv/bin/pip install -U "yt-dlp[default]"`

## 1. 一条命令出视频
```bash
.venv/bin/python pipeline/make_mv.py --name X --url "LINK" --lang ja --title "《歌名》 歌手" --keep-frames
```
各阶段：
- **download / prep**：下载最高 2160p；降到 1080p 供插帧；导出 FLAC 48k/24bit
- **lyrics**：官方字幕（`--sub-lang`）→ `ori_lyrics/X.srt`；否则 `get_ytb_lyrics_from_link.py` → `ori_lyrics/X.txt`（识别不准时 `--song-title/--artist` 或 `--genius-url`）。现场版歌词可能与录音室版不同，提醒用户过一眼
- **separate**：Mel-Band RoFormer（KimberleyJensen vocals 权重）分离人声 → `separated/roformer/X/vocals.wav`
- **align**（见第 2 节）→ `ori_lyrics/X.srt`
- **translate**：DeepSeek（`.env`，思考 high）翻译 → `lyrics/X.ass`
  - **按句缓存** `work/X/zh_cache.json`，时间轴重做不重复翻译；只翻新句，整首歌词作上下文
  - **语气词不翻译**（oh / yeah / ah…），`strip_interjections` 兜底；片假名按外来语还原，不输出“意义不明”
  - **标题行加中文**（通行译名，如 Linkin Park → 林肯公园、そばにいるね → 在你身边），和歌词里的译名一致
  - 样式与 bzrp_v2 一致：384x288 画布、Arial Rounded 23、描边 1、底边距 50，`原文 \N♪ 中文 ♪`（`build_ass_bzrp`）
- **interp**：原生帧率抽帧，RIFE v4.6 `-n` 一步插到 60fps；按磁盘余量自动选 png/jpg
- **render**：lanczos 到 4K → 烧字幕 → 水印 → x264 crf18 + FLAC。只改字幕时 `--from translate`（需 `--keep-frames`）；`--tag` 出对比版本
- 校验：ffprobe 看 3840x2160 / 60/1 / 帧数 / 时长与源一致 / flac 48000 24bit；抽帧看字幕、水印

## 2. align：时间轴（核心）
目标：声音时间轴和字幕时间轴高度匹配；拿不准宁可不出，也不出错句。

### A. 官方带时间字幕
官方时间轴是人工打的，实测任何重解码都会变差 → 只做 `split_long` + `acoustic.py --mode post`（拖音延长、短空档桥接、句尾收紧）。

### B. Genius 歌词文本（现场版常见：改编、删减、重复、对唱、说唱）
1. **`qwen_sequence.py`**：人声在安静处切 10~20s 块，逐块 `qwen3-asr-flash`（百炼 OpenAI 兼容接口，`ALIYUN_BAILIAN_API_KEY`，与 Takit 相同）识别，按读音匹配参考句 → 这一版实际演唱的句子顺序 `work/X/sung_order.txt` + 每句所在块 `sung_order.json`。**不要给 Qwen 传歌词上下文**，它会原样照抄
2. **`chunk_align.py`**：每块的句子序列，在块的时间范围（±0.8s）里用 MMS_FA 按顺序强制对齐
3. `split_long.py`：超过 40 宽（全角算 2）的句子在停顿处拆开
4. **先** `infer_insert.py`：Qwen 漏掉的句子（说唱、对唱）——相邻句之间 ≥2s 有人声却没字幕，按参考歌词顺序推断该唱的句子，时长相符就插入；句间重复词修正（前句以 “I” 结尾、后句又以 “I” 开头 → 换成参考里不带的写法）。**必须在拖音/桥接之前**，否则空档被拉长的上一句盖住
5. `refine_timing.py`：全曲强制对齐精修起止、吸附起音、字幕提前 `--lead 0.12s`、时长体检（被拉长/挤短的句子按字数重新分配）
6. `acoustic.py --mode post --no-fill-gaps`：拖音延长（语气词句最多 +0.5s）、短空档桥接（<3.5s 且多半有人声 → 前一句保持）、句尾收紧
7. **`verify_qwen.py`**：每句字幕的人声单独截出（±0.3s）给 Qwen 识别比对：≥65 保留；明显是另一句（≥75 且高出 15）就换；<30 隐藏；其余可疑句保留并列在 `work/X/verify_report.json`。429 限流自动退避，并发 3
8. `split_long.py`

用户反馈“某时间点不对”时：先看 `sung_order.json` 那一块 Qwen 认出了哪些句、`verify_report.json` 里有没有可疑，再定位是哪一步出的问题；只汇报句号和时间，不贴歌词。

### 演进记录（试过、被替代的）
whisper 定结构 + 强制对齐；纯 MMS 声学全局解码（对唱段整段留空、副歌乱跳）；Qwen 滑窗锚点加分（插句暴增）；全局解码 + 邻句推断（把 Qwen 已认对的顺序改乱）；歌词作 whisper/Qwen 提示（无效 / 照抄）。分块对齐 + 逐句复核在 HKT48 现场上：逐句复核通过 48 → 51+、可疑 11 → 2 处被隐藏。

### 提前量
`--lead 0.12` 已含在 align 里。渲染时 `--sub-shift` 再整体提前，精校后一般不需要；用户偏好可试 0.1~0.2。

## 3. 封面（16:9 + 4:3）
```bash
.venv/bin/python pipeline/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中日字幕" --at 65.2 [--inpaint-subs] [--text-y 0.80]
```
- 优先人物特写（`--at` 指定时间，可从用户截图里的字幕在 srt 里反查时间）；选中的帧 Real-ESRGAN x4 高清化（`--no-sr` 关闭）
- 统一元素：左上水印 + 4K60 徽章；标题撑满 94% 宽，副标题与标题等宽对齐；副标题基线 `--text-y`（默认 0.66，脸在画面中段时调到 0.75~0.80，不超过 0.84）
- 每张同时出 16:9 `cover_XX.jpg` 和 4:3 `cover_XX_4x3.jpg`（4:3 裁切窗口自动对准人脸）
- 画面烧了字幕：`--inpaint-subs`（按白字定位字幕框，用周围画面修补）
- 专辑图等外部图：`--image cover/X_art.png --fill extend`（去边条、放大、两侧只延伸背景色）
- 选定后 `cover/` 只留 `cover_01.jpg` 和 `cover_01_4x3.jpg`

## 4. 投稿元数据 JSON
```bash
.venv/bin/python pipeline/make_meta.py --name X --subtitle-langs "日语,中文" --note "演出名称、日期、场地、场次等"
```
- 标题 `[4K60帧/Hi-Res] 中文名《歌名》英文名 关键词`，≤80 字
- **生成后逐条核对并手改**：模型常把频道口号当演出细节、给罗马字人名乱配汉字、编造材料里没有的事实（吉尼斯纪录、乐队伴奏等）、用“国民级”之类无依据的夸张；不写不确定的成员名字

## 5. 收尾
用户确认后：成品去掉 `--tag` 后缀（或重命名）、JSON 路径同步；删对比版；字幕不再改就删 `work/X/frames_in|frames_out`；代码改动提交推送。
