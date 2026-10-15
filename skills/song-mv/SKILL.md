---
name: song-mv
description: 给一个歌曲视频链接（YouTube 等），产出 4K + 60帧插帧 + 水印 + 原文/中文双语歌词 + FLAC Hi-Res 的成品视频，以及 B 站投稿用的 16:9 / 4:3 封面和元数据 JSON。当用户给出歌曲链接并要求“做视频 / 出 4K60 / 加双语字幕 / 做封面 / 投稿信息”时使用。
---

# 歌曲 4K60 双语视频流程

一律用 `.venv/bin/python` 运行；人声分离用 `.venv-sep`（make_mv 会自动调用）。安装见 README。

| 入口 | 作用 |
|---|---|
| `workflow/make_mv.py` | 视频总控：`download → prep → lyrics → separate → align → translate → interp → render`，`--from/--to` 断点续跑 |
| `workflow/make_cover.py` | 封面：16:9 + 4:3 |
| `workflow/make_meta.py` | 投稿元数据 JSON |
| `workflow/get_ytb_lyrics_from_link.py` | YouTube 链接 → Genius 歌词 → `posts/<name>/lyrics.txt`（lyrics 阶段自动调用） |
| `workflow/eval_subs.py` | 字幕时间轴客观评测，多版本对比 |

产物：每个作品一个目录 `posts/X/` 一首歌一个目录：参考歌词 `lyrics.txt`/`official.srt` → 对齐字幕 `lyrics.srt` → 双语 `lyrics.ass`；中间文件（source.mp4、audio.flac、vocals.wav、reports/、frames_*）；成品在 `posts/X/post/`（视频 + `cover/` + `X.json`）。路径约定见 `workflow/paths.py`。

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
.venv/bin/python workflow/make_mv.py --name X --url "LINK" --lang ja --title "《歌名》 歌手"
```
各阶段：
- **download / prep**：下载最高 2160p；降到 1080p 供插帧；导出 FLAC 48k/24bit
- **lyrics**：官方字幕（`--sub-lang`）→ `posts/X/lyrics.srt`；否则 `get_ytb_lyrics_from_link.py` → `posts/X/lyrics.txt`（识别不准时 `--song-title/--artist` 或 `--genius-url`）。现场版歌词可能与录音室版不同，提醒用户过一眼
- **separate**：Mel-Band RoFormer（KimberleyJensen vocals 权重）分离人声 → `posts/X/vocals.wav`
- **align**（见第 2 节）→ `posts/X/lyrics.srt`
- **speech**：单独一条流程，和歌词分开。歌词之外的说话（开场白、谢幕；`--speech-gaps` 也处理曲中长空档）按停顿切句、逐句 Qwen 识别 → `posts/X/speech.srt`；`--no-speech` 关闭。多句段落按句号拆开、逐句局部强制对齐校准；说话不是歌词，用识别文字；字幕用单独的 **Speech 样式（暖黄色）**，中文不加 ♪
- **translate**：DeepSeek（`.env`，思考 high）翻译 → `posts/X/lyrics.ass`；说话字幕一起翻，中文不加 ♪
  - **先整首解读再逐句意译**：第一步让模型通读整首写“歌曲解读”（故事线、人物、俚语/双关/隐喻在这首里的真实含义，缓存在 `__brief__`），逐句翻译时带上它；意译优先，读不通的直译（把比喻、黑话按字面硬翻）不要。`--retranslate` 忽略缓存整首重翻
  - **按句缓存** `posts/X/zh_cache.json`，时间轴重做不重复翻译；只翻新句，整首歌词作上下文
  - **语气词不翻译**（oh / yeah / ah…），`strip_interjections` 兜底；片假名按外来语还原，不输出“意义不明”
  - **标题行加中文**（通行译名，如 Linkin Park → 林肯公园、そばにいるね → 在你身边），和歌词里的译名一致
  - 样式与 bzrp_v2 一致：384x288 画布、Arial Rounded 23、描边 1、底边距 50，`原文 \N♪ 中文 ♪`（`build_ass_bzrp`）
- **interp**：原生帧率抽帧，RIFE v4.6 `-n` 一步插到 60fps；按磁盘余量自动选 png/jpg
- **render**：lanczos 到 4K → 烧字幕 → 水印 → x264 crf18 + FLAC。插帧帧序列 `frames_out` 默认保留（换字幕/对齐方案只需 `--from translate` 重新渲染）；`--tag` 出对比版本，**重新渲染前先给旧版改名或用 `--tag`，别直接覆盖**；`frames_in` 插帧后自动删
- 校验：ffprobe 看 3840x2160 / 60/1 / 帧数 / 时长与源一致 / flac 48000 24bit；抽帧看字幕、水印

## 2. align：时间轴（核心）
目标：声音时间轴和字幕时间轴高度匹配；拿不准宁可不出，也不出错句。

### A. 官方带时间字幕
官方时间轴是人工打的，实测任何重解码都会变差 → 只做 `split_long` + `acoustic.py --mode post`（拖音延长、短空档桥接、句尾收紧）。

### B. Genius 歌词文本（默认 `--align-mode dense`）
**有 `lyrics_sections.txt`（lyrics 阶段用 `--keep-sections` 自动多抓一份）时按段落对齐（`qwen_dense --order sections`）**：
段内严格按歌词顺序、一句不漏（跳句重罚），段与段之间按现场顺序跳转/重复（由密集窗口证据决定）；被识别证实的句子不到 30% 的段落视为没唱（防止开场说话误配）；单句时长上限 8s。
这是尊重歌词和跟上现场结构的折中：纯按歌词顺序（`--order lyrics`）在现场改顺序时整段错位；纯逐窗匹配（`--order free`）在说唱等识别困难处漏句。
Lose Yourself 实测：87 句全部输出，段落顺序 Intro→V1→Chorus→V2→Chorus→V3→Chorus→Outro。

1. **`qwen_dense.py`**：人声按 **2.5s 窗口、0.5s 步长** 逐窗 qwen3-asr-flash 识别（缓存 `reports/dense_cache.json`），每窗按读音匹配参考里最像的一句，连续同句合并成一段 → 每句大致位置。窗口足够短，能分清副歌和长得像的尾段/改编段（10~20s 大块分不清，Lose Yourself 2:42–3:06、4:17–5:15 因此整段错成副歌）。**不要给 Qwen 传歌词上下文**，它会照抄
2. 逐句**局部**强制对齐（每句只在自己的位置 ±0.6s 内用 MMS 收紧起止，不跨句）。**不要再跑全曲 refine_timing**：它假设按歌词顺序唱，会把重复段落拉错（实测把错误窗口从 10 推到 62）
3. `acoustic.py --mode post --no-fill-gaps`：拖音延长、短空档桥接、起点校正、句尾收紧
4. 日文/中文才 `split_long`；英文、意大利语等一行歌词就是一条字幕，长行自动换行 + 缩小字号
实测 Lose Yourself 2:30–5:16：错句窗口 78 → 16。旧方法保留为 `--align-mode qwen`（10~20s 分块 + 推理补句 + 逐句复核）和 `lyrics`（完全按歌词顺序）。

用户反馈“某时间点不对”时：先看 `sung_order.json` 那一块 Qwen 认出了哪些句、`verify_report.json` 里有没有可疑，再定位是哪一步出的问题；只汇报句号和时间，不贴歌词。

### 演进记录（试过、被替代的）
whisper 定结构 + 强制对齐；纯 MMS 声学全局解码（对唱段整段留空、副歌乱跳）；Qwen 滑窗锚点加分（插句暴增）；全局解码 + 邻句推断（把 Qwen 已认对的顺序改乱）；歌词作 whisper/Qwen 提示（无效 / 照抄）。分块对齐 + 逐句复核在 HKT48 现场上：逐句复核通过 48 → 51+、可疑 11 → 2 处被隐藏。

### 提前量
`--lead 0.12` 含在 align 里；渲染时 `--sub-shift` 默认再整体提前 **0.2s**（用户在 0 / 0.1 / 0.2 / 0.3 四档对比后选定），标题行不动。

## 3. 封面（16:9 + 4:3）
```bash
.venv/bin/python workflow/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中日字幕" --at 65.2 [--inpaint-subs] [--text-y 0.80]
```
- 优先人物特写（`--at` 指定时间，可从用户截图里的字幕在 srt 里反查时间）；选中的帧 Real-ESRGAN x4 高清化（`--no-sr` 关闭）
- 统一元素：左上水印 + 4K60 徽章；标题撑满 94% 宽，副标题与标题等宽对齐；副标题基线 `--text-y`（默认 0.66，脸在画面中段时调到 0.75~0.80，不超过 0.84）
- 每张同时出 16:9 `cover_XX.jpg` 和 4:3 `cover_XX_4x3.jpg`（4:3 裁切窗口自动对准人脸）
- 画面烧了字幕：`--inpaint-subs`（按白字定位字幕框，用周围画面修补）
- 专辑图等外部图：`--image posts/X/cover_art.png --fill extend`（去边条、放大、两侧只延伸背景色）
- 选定后 `posts/X/post/cover/` 只留 `cover_01.jpg` 和 `cover_01_4x3.jpg`

## 4. 投稿元数据 JSON
```bash
.venv/bin/python workflow/make_meta.py --name X --subtitle-langs "日语,中文" --note "演出名称、日期、场地、场次等"
```
- 标题 `[4K60帧/Hi-Res] 中文名《歌名》英文名 关键词`，≤80 字
- **生成后逐条核对并手改**：模型常把频道口号当演出细节、给罗马字人名乱配汉字、编造材料里没有的事实（吉尼斯纪录、乐队伴奏等）、用“国民级”之类无依据的夸张；不写不确定的成员名字

## 5. 收尾
用户确认后：成品去掉 `--tag` 后缀（或重命名）、JSON 路径同步；删对比版；字幕不再改就用 `--clean-frames` 或手动删 `posts/X/frames_out`；代码改动提交推送。
