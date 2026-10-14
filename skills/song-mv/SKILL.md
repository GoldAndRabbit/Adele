---
name: song-mv
description: 给一个歌曲视频链接（YouTube 等），产出 4K + 60帧插帧 + 水印 + 原文/中文双语歌词的成品视频，以及 B 站投稿用的 16:9 / 4:3 封面和元数据 JSON。当用户给出歌曲链接并要求“做视频 / 出 4K60 / 加双语字幕 / 做封面 / 投稿信息 / 按 bzrp 流程”时使用。
---

# 歌曲 4K60 双语视频流程

一律用 `my_venv/bin/python` 运行（里面有 yt-dlp / whisper / demucs / pysubs2 / openai / pykakasi / rapidfuzz）。

| 脚本 | 作用 |
|---|---|
| `pipeline/make_mv.py` | 总控，阶段 `download → prep → lyrics → split → translate → interp → render`，`--from/--to` 断点续跑 |
| `pipeline/fill_whisper_gaps.py` | 补 whisper 漏识别的段落（lyrics 阶段自动调用） |
| `pipeline/align_lyrics.py` | 原始歌词 ↔ whisper 互相校准（有参考歌词时 lyrics 阶段自动调用） |
| `pipeline/split_long.py` | 长句在停顿处拆开（split 阶段） |
| `pipeline/translate_ass.py` | 双语 ass（translate 阶段） |
| `pipeline/make_cover.py` | 封面：16:9 + 4:3 |
| `pipeline/make_meta.py` | 投稿元数据 JSON |
| `pipeline/llm.py` | 模型调用，密钥读仓库根目录 `.env`（与 Takit 同名变量，默认 DeepSeek） |

产物目录：**每个作品一个文件夹** `post/X/`：`X 4K60FPS Sub-WaterMark.mp4` + `cover/` + `X.json`。中间文件在 `work/X/`。

## 硬性要求
- **音轨必须是 FLAC 48kHz/24bit**（B 站 “Hi-Res无损” 标靠它）。render 阶段强制 `-c:a copy` 放 flac，渲染后自动检查，不符直接报错；不要改成 AAC
- **歌词文本和译文不由 Claude 自己写**：来源只能是官方字幕、whisper 识别、用户提供/自己保存的歌词文件、翻译 API。用户贴在对话里的歌词，请用户自己存成 `ori_lyrics/X.txt`
- 投稿 JSON 里的事实必须有出处（视频简介、用户提供、可查证的资料），模型生成后要人工核对

## 0. 先确认参数
- `--name`：短名，全部文件以它命名
- 是否截取 `--start/--end`（直播/合集常需要；先 `--to download` 看时长）
- `--lang English|Spanish|Japanese...`（whisper），`--sub-lang en|es|ja`（官方字幕）
- 视频是否自带烧录字幕（搬运视频常见）：字幕默认样式离底部约 17%，一般不会和底部烧录字幕重叠；封面取帧要用 `--crop-bottom`

## 1. 下载 + 预处理 + 原文歌词
```bash
my_venv/bin/python -m pip install -U "yt-dlp[default]"   # YouTube 经常变；[default] 带 JS 验证解析器
my_venv/bin/python pipeline/make_mv.py --name X --url "LINK" --lang Japanese --sub-lang ja --to lyrics
```
- 报 “Sign in to confirm you’re not a bot” → `--cookies-from-browser chrome`（先征得用户同意）
- **有官方人工字幕**：直接用，产物 `ori_lyrics/X.srt`
- **没有官方字幕**：demucs 分离人声 → whisper large-v3（逐字时间戳 json）→ **自动补漏**：人声明显很响、但 whisper 超过 5s 没识别的区间（现场录音的开头最常见），单独截出来从几个起点重识别，取词最多的结果合并回去
- **有原始歌词就自动互相校准**（强烈建议）：歌词放 `ori_lyrics/X.txt`（一行一句；`[Verse]` 段落标记会自动去掉；顺序不必与这一版一致）或 `--ref-lyrics path`（txt/srt，比如同一首歌其他视频的官方字幕）
  - 以录音为主导：两边转平假名读音（pykakasi），把参考歌词拆成短语，整段识别连成一条流从头扫，在任意位置模糊匹配参考短语（rapidfuzz），可跨 whisper 片段、可乱序、可重复；同一原句相邻短语再合并
  - **默认 reference 模式**：文字只来自参考歌词、按顺序逐句定位，whisper 只用来定时间；识别里有、参考里没有的内容一律不进字幕。没定位到的句子：前后空档够唱 → 插值时间；空档不够（删减版/现场没唱）→ 丢弃，不能把没唱的词放上去。报告列出插值和丢弃的行
  - 翻译输入只有参考歌词文本；DeepSeek 默认开 high 思考（`TRANSLATE_EFFORT` 可改），片假名按外来语还原，不输出“意义不明”
  - `--align-mode recording`：以录音为主、对不上的保留 whisper 原文（只在参考歌词不全或顺序完全不同时用）
  - 现场版识别差时放宽门槛：`--align-min-score 70 --align-min-cover 0.6`（默认 80 / 0.7）
  - 报告 `work/X/align_report.json`：`from_whisper_needs_review` 是需要用户核对的时间点

## 2. 人工校对（检查点）
把需核对的时间点给用户，让用户改 `ori_lyrics/X.srt` 的文字，**时间轴不动**。
Claude 只做格式层面的检查（时长、重叠、句数、覆盖范围、开头是否漏识别），汇报时只给统计和时间点，不贴歌词。

## 3. 拆长句 + 双语字幕
```bash
my_venv/bin/python pipeline/make_mv.py --name X --from split --to translate --title "《歌名》 歌手"
```
- split：超过 40 宽（全角算 2）的句子在空格/标点处拆开，切点对齐 demucs 人声能量最低处（换气）；`--max-width` 可调
- translate：DeepSeek 翻译（`.env` 里 `LLM_PROVIDER` 可切 aliyun / siliconflow / openai）；或 `--zh-file zh.txt`（每行对应一句）
- 产物 `lyrics/X.ass`，默认样式与 `lyrics/bzrp_v2.ass` 一致（384x288、Arial Rounded 23、描边 1、底边距 50，`原文 \N♪ 中文 ♪`，标题作为首行在底部）；`--sub-style modern` 是 1080p 画布 + 日文粗体 + 标题在顶部
- 已存在的文件不覆盖，重新生成加 `--force`
- 歌名的通行中文译名要准确（例：そばにいるね = 在你身边，不是“留在我身边”）

## 3.5 时间轴精校（refine 阶段，split 和 translate 之间自动跑）
目标：字幕文字只来自参考；声音时间轴和字幕时间轴高度匹配；拿不准宁可不出也不出错句。**按参考来源分流**（lyrics 阶段写 `work/X/lyrics_source`）：

### A. 只有歌词文本（txt，Genius 等）→ RoFormer 人声 + Qwen 演唱序列 + 声学全局解码（V13）
核心思路：**结构（唱了哪些句、什么顺序、大概在哪一块）交给最会“听”歌的 Qwen3-ASR；精确时间交给 MMS 强制对齐**。whisper 只用来估计演唱速率。
1. `separate_roformer.py`（独立环境 `sep_venv`）：Mel-Band RoFormer（KimberleyJensen vocals 权重，HuggingFace）分离人声，比 demucs 干净；模型代码在 `third_party/mss`（ZFTurbo，git clone），权重 `third_party/models/MelBandRoformer.ckpt`。raw.githubusercontent.com 在本机证书被劫持，audio-separator 下不了模型，所以走 HF + git clone
2. `qwen_sequence.py`：人声在安静处切 10~20s 块，逐块 `qwen3-asr-flash`（百炼 OpenAI 兼容接口，密钥 `ALIYUN_BAILIAN_API_KEY`，与 Takit 相同）识别，按读音从左到右贪心匹配参考句 → 这一版的演唱序列 `work/X/sung_order.txt` + 每句所在时间块 `sung_order.json`。**不要给 Qwen 传歌词上下文**：它会把上下文原样照抄回来
3. `decode_global.py --strict-order true --windows sung_order.json --skip-cost 100 --seg-cost 0`：按演唱序列严格顺序、每句只能落在所在块 ±2s 内、每句都必须放，MMS 打分图 + 全局 DP 定位置
4. `split_long.py` → `refine_timing.py`（强制对齐精修、起音吸附、提前 0.12s、时长体检）→ `acoustic.py --mode post`（补空档、挤压句摊开、拖音延长、句尾收紧）→ `split_long.py`

### B. 官方带时间字幕（srt）→ 保留官方时间轴，只做 `acoustic.py --mode post`
官方时间轴是人工打的，实测任何重解码都会变差（青山テルマ：官方 75% 踩点，V8 59%，旧精校 69%）。

### 实测（评测脚本 `eval_subs.py`）
| 歌 | 方案 | 踩点 | 错位嫌疑 | 人声覆盖 |
|---|---|---|---|---|
| HKT48 现场（删减改编，歌词文本） | 精校前 → V8c | 27% → **83%** | 14 → **0** | 87% → 89% |
| Linkin Park 现场（歌词文本） | 精校前 → V8c | 36% → **72%** | 12 → **1** | 79% → **94%** |
| 青山テルマ（官方字幕） | 官方 → 官方+后处理 | 75% → 74% | 14 → 13 | 98% → 98% |

### 演进记录（试过、被替代或弃用的）
- V8 纯声学全局解码（无 Qwen）：对唱/现场改编段落声学分数低，整段被判“没唱”留空（HKT48 1:06）；副歌重复时乱跳
- Qwen 8s 滑窗锚点直接加分：窗口太粗，同一句被反复插入（句数暴增、错位变多）
- 严格模式下“文字相同的下一句也算顺着唱”：重复副歌之间乱跳，已改为只有紧接的下一句算
- whisper 文字定结构 + 强制对齐 + 混合重解码（V1–V7）：一直在给 whisper 的结构错误打补丁（漏句被当没唱→前后句被挤压/拉长/留空）
- whisper 用歌词作 initial_prompt 重识别（`prompt_rerun.py`）：几乎无变化
- 纯声学重解码整段替换：错句清零但误删效果器段落的正确句
- V8 宽松顺序用于官方字幕：过度插入重复句（71→106 句）

`--sub-shift 0.3`：渲染时再整体提前 0.3s（人眼对画面变化反应快）。只重做时间轴不重翻译：句子没变时从 ass 抽中文做 `--zh-file`，否则 `--from translate --force`。

## 4. 插帧 + 渲染
```bash
my_venv/bin/python pipeline/make_mv.py --name X --from interp --keep-frames
```
- 可以在 lyrics 阶段跑的同时并行插帧（RIFE 用 GPU，whisper 用 CPU）
- 降到 1080p 后按**原生帧率**抽帧，RIFE v4.6 `-n` 一步插到 60fps；源已是 60fps 则跳过
- PNG 帧按磁盘余量自动选 png/jpg（`--frame-format` 可指定）
- lanczos 放大到 3840x2160 → 烧 ass → 左上角 `adele-logo.png` → x264 crf18 + FLAC
- 只改字幕时 `--from render`（需要之前 `--keep-frames`）；对比不同版本用 `--ass 文件 --tag 后缀`
- `--sub-shift 0.3`：渲染时字幕整体再提前 0.3s（叠加在 refine 的 0.12s 提前量之上），人眼对画面变化反应快，提前一点更跟手；标题行不动
- 校验：ffprobe 看 3840x2160 / 60/1 / 帧数 / 时长与源一致 / flac 48000 24bit；抽一帧看字幕、水印、是否压到烧录字幕

## 5. 封面（16:9 + 4:3）
```bash
my_venv/bin/python pipeline/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中日字幕" [--at 60 --at 120] [--crop-bottom 0.14]
```
- 默认从原视频均匀取 48 帧、按清晰度挑 6 张；自动挑的常是全景，**优先用 `--at` 指定人物特写**：脸在画面上半部分、标题落在下巴以下
- 每张同时出 **16:9 `cover_XX.jpg`（1920x1080）和 4:3 `cover_XX_4x3.jpg`（1440x1080）**，B 站两种都要；4:3 单独排版，裁切窗口自动对准画面上部细节最多处（人脸），不会裁掉半张脸
- 统一元素：左上 朝阳Adele logo（深色衬底）+ `4K60-logo.jpg` 徽章（自动圆角、描边、投影），中部大标题 + 宋体副标题，副标题基线默认 0.66 高度（`--text-y`，不要超过 0.84）
- 标题撑满到接近左右边缘（`--title-width 0.94`，字号上限 30% 画面高）；副标题字号尽量大、与标题**左右等宽对齐**（字号封顶时自动加字距）
- 选中的帧默认做 **Real-ESRGAN x4 高清化**（原分辨率截帧 → x4 超分 → Lanczos 缩到封面尺寸），约 20s/帧；`--no-sr` 关闭
- 画面里烧了字幕的视频：**优先 `--inpaint-subs`**（按白字定位字幕框，用周围画面修补，保持选定帧和构图；需要 opencv-python-headless==4.11.0.86，别让它把 numpy 升到 2.3+）；其次 `--mask-bottom 0.14`（底部条带模糊压暗，保持原构图，人脸更靠上，标题能放在默认高度）；`--crop-bottom 0.14` 会裁切放大，特写的脸偏大偏下，标题得放低到 0.80 才不压脸
- 特写镜头里人脸占画面中段时标题很难放高，优先挑人脸在画面上 1/3 的帧（如两人同框的中景）
- 右上角额外 logo：`--extra-logo path.png`；标题字体 `--title-font gill|serif`
- 用专辑封面等外部图：`--image cover/X_art.png`，自动去边条、分辨率不足先 Real-ESRGAN x4；方图补成横版用 `--fill extend`（只延伸背景色，推荐）
- 选定后 `cover/` 里只留 `cover_01.jpg` 和 `cover_01_4x3.jpg`

## 6. 投稿元数据 JSON
```bash
my_venv/bin/python pipeline/make_meta.py --name X --subtitle-langs "日语,中文" --note "演出名称、日期、场地、场次等补充"
```
- 依据 `work/X/meta.json`（yt-dlp 抓的标题/简介/日期）+ `--note`，产物 `post/X/X.json`
- 字段：title（`[4K60帧/Hi-Res] 中文名《歌名》英文名. 关键词`，≤80 字）、song、performance、intro.song、intro.performance、tags、subtitles、spec、files（video / cover / cover_4x3 / subtitle）、source
- **生成后逐条核对并手动改**，模型常见错误：
  - 把频道口号当演出细节（如 THE FIRST TAKE 的“一支麦克风”）
  - 给罗马字人名乱配汉字
  - 编造材料里没有的事实（吉尼斯纪录、现场乐队伴奏等），换成有出处的说法或删掉
  - 无依据的夸张（“国民级”）；不写不确定的成员名字

## 7. 收尾
用户确认成品后：
- 删对比版/草稿视频，`post/X/` 只留成品、`cover/` 两张封面、`X.json`
- 字幕不再改了就删 `work/X/frames_out/`（几十 GB）
- 代码改动提交并推送（`git push`）
