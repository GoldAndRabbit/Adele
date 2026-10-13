---
name: song-mv
description: 给一个歌曲视频链接（YouTube 等），产出 4K + 60帧插帧 + 水印 + 原文/中文双语歌词的成品视频。当用户给出歌曲链接并要求“做视频 / 出 4K60 / 加双语字幕 / 按 bzrp 流程”时使用。
---

# 歌曲 4K60 双语视频流程

脚本：`pipeline/make_mv.py`（总控），`pipeline/translate_ass.py`（双语 ass）。
一律用 `my_venv/bin/python` 运行（里面有 yt-dlp / whisper / demucs / pysubs2 / openai）。

## 0. 先确认参数
- `--name`：短名，全部文件以它命名（如 `bzrp`）
- 是否需要截取片段 `--start/--end`（直播/合集视频常需要；先 `--to download` 下载后看时长再定）
- 歌曲语言：`--lang English|Spanish|Japanese...`（whisper 用），`--sub-lang en|es|ja`（官方字幕用）
- 标题行 `--title "《歌名》 歌手"`

## 1. 下载 + 预处理 + 原文歌词
```bash
my_venv/bin/python -m pip install -U yt-dlp   # YouTube 经常变，先升级
my_venv/bin/python pipeline/make_mv.py --name X --url "LINK" --lang Spanish --sub-lang es --to lyrics
```
- 报 “Sign in to confirm you’re not a bot” → 加 `--cookies-from-browser chrome`（先征得用户同意）
- 有官方人工字幕就用它，否则 demucs 分离人声 + whisper large-v3 识别；`--whisper` 可强制识别
- 产物 `ori_lyrics/X.srt`
- **有原始歌词时自动互相校准**：把歌词放到 `ori_lyrics/X.txt`（一行一句、按演唱顺序）或用 `--ref-lyrics path`（txt/srt）。`pipeline/align_lyrics.py` 字符级对齐，文字取歌词、时间取 whisper 逐字时间戳；报告 `work/X/align_report.json` 列出低置信度句和“唱了但歌词里没有”的段落

## 2. 人工校对原文（检查点）
whisper 结果经常有错字/漏句。让用户对照正确歌词修改 `ori_lyrics/X.srt` 的文字，**时间轴不动**。
可帮用户做格式层面的检查（时间重叠、空行、明显的重复幻听行、开头静音段的幻觉文本），但歌词文本和翻译内容不要由 Claude 自己写出——来源只能是官方字幕、whisper 识别、用户提供的文本或翻译 API。

## 3. 双语字幕
```bash
my_venv/bin/python pipeline/make_mv.py --name X --from translate --to translate --title "《歌名》 歌手"
```
- 密钥读仓库根目录 `.env`（与 Takit 相同的变量名，默认 `LLM_PROVIDER=deepseek`，模型 deepseek-v4-pro；可切 aliyun / siliconflow / openai）
- 或用户自备中文：`--zh-file zh.txt`（每行对应 srt 一句，空行 = 不翻译）
- 产物 `lyrics/X.ass`：默认样式与 `lyrics/bzrp_v2.ass` 一致（384x288、Arial Rounded 23、描边 1、底边距 50，`原文 \N♪ 中文 ♪`，标题作为首行在底部）；`--sub-style modern` 为 1080p 画布 + 日文粗体 + 标题在顶部
- 已存在的文件不会被覆盖，重新生成要 `--force`

## 4. 插帧 + 渲染
```bash
my_venv/bin/python pipeline/make_mv.py --name X --from interp
```
- 降到 1080p 后按**原生帧率**抽帧，RIFE v4.6 `-n` 一步插到 60fps（24/25/30 都适用，不再先 dup 到 30）
- 源已是 60fps 则跳过插帧
- lanczos 放大到 3840x2160 → 烧 ass → 左上角 `adele-logo.png`（宽度 10%）→ x264 crf18 + AAC 320k
- `--fast` 用 VideoToolbox HEVC 硬编；`--keep-frames` 保留 PNG
- 成品：`post/X/X 4K60FPS Sub-WaterMark.mp4`（每个作品一个目录：视频 + `cover/` + `X.json`）

## 注意
- 1080p PNG 帧约 3MB/帧，4 分钟 60fps ≈ 14400 帧 ≈ 40GB，开工前 `df -h` 看磁盘
- 校验成品：`ffprobe` 看 3840x2160 / 60/1 / 时长与音频一致；抽一帧截图看字幕和水印
- 只改了字幕时只需 `--from render`（需 `--keep-frames` 保留过帧，否则从 `interp` 重来）

## 5. 封面候选
```bash
my_venv/bin/python pipeline/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中英字幕"
```
- 从原始 4K 视频均匀取 48 帧，按清晰度/亮度挑 6 张（`--n` 改数量，`--at 65.2` 指定时间点）
- 每张统一打上：左上 朝阳Adele logo（带深色衬底）+ 金色 4K/60FPS 徽章，中下方大标题 + 宋体副标题，副标题基线默认在 68% 高度（`--text-y` 调，越小越靠上；不要超过 0.84，底部留给 B 站播放量）
- 右上角额外 logo（队徽等）：`--extra-logo path.png`，可多次
- 标题字体：英文默认 Avenir Next Heavy，含日文/中文自动用 Hiragino Sans W8；`--title-font gill|serif` 可换成 Bzrp / Man of the Year 那种风格
- 产物：`post/X/cover/candidates.jpg`（编号总图，给用户挑）、`cover_XX.jpg`（1920x1080 成品）、`frame_XX_*.jpg`（原始帧）

### 用专辑封面等外部图片
```bash
my_venv/bin/python pipeline/make_cover.py --name X --title "歌名" --subtitle "..." --image cover/X_art.png --out-dir post/X/cover/art
```
- 自动去掉左右纯色边条；分辨率不够先用 Real-ESRGAN x4 放大
- 非 16:9 的图：`--fill extend`（边缘颜色向两侧延伸，默认推荐）/ `blur`（模糊底图）/ `crop`

## 6. 投稿元数据 JSON
```bash
my_venv/bin/python pipeline/make_meta.py --name X --subtitle-langs "日语,中文" --cover post/X/cover/cover_01.jpg [--note "补充信息"]
```
- 依据 `work/X/meta.json`（yt-dlp 抓的标题/简介/日期）让模型整理，产物 `post/X/X.json`
- 字段：title（`[4K60帧/Hi-Res] 中文名《歌名》英文名. 关键词`，≤80 字）、song、performance、intro.song、intro.performance、tags、subtitles、spec、files、source
- 生成后**必须人工核对**：模型可能把频道口号当演出细节、给罗马字人名乱配汉字、编造数字
