# Lyrics Rolling Video

竖屏歌词气泡视频实验模块：小角度整页透视、双语歌词、正式「朝阳 Adele」Logo、按词组移动和伸缩的半透明气泡。

当前样片为 Vegedream《Ramenez la coupe à la maison》原曲 **70.5–83.9 秒（13.4 秒）**，包含 10 行排版、18 个词组。时间由实际音频自动对齐，不是均分句子时长；尚需人工试听确认，不代表整首歌曲已经完成。

## 怎么看预览

在项目根目录执行：

```bash
python3 lyrics_rolling_video/serve.py
```

终端显示地址后，打开 **http://127.0.0.1:8765/**，点击「播放」。保持终端运行，按 `Ctrl+C` 结束服务。也可以进入本目录后执行 `python3 serve.py`，脚本不依赖当前工作目录。

如果提示端口已占用，先检查已经打开的 8765 是否就是预览页；否则改用另一个端口，不需要停止其他服务：

```bash
python3 lyrics_rolling_video/serve.py --port 8766
```

打开 **http://127.0.0.1:8766/**。服务只监听本机，只提供 `preview/` 内容，不暴露项目根目录。

预览支持：

- 播放 / 暂停、从头播放、进度拖动、循环播放。
- 0.5× / 0.75× / 1× / 1.5× 速度；音频和气泡一起变化。
- 气泡时间微调：负值提前，正值延后，范围 ±500 ms。此设置只影响当前网页，不会写回时间轴或影响视频导出。
- 空格播放 / 暂停，左右方向键跳转 1 秒（控件获得焦点时保留其原有键盘操作）。

本机已保留音频和生成的预览，直接启动即可。**新克隆的仓库不包含音频或生成页面**，请先按下文准备素材。

## 目录说明

```text
lyrics_rolling_video/
  README.md
  config.json                # 歌曲资料、截取范围、校对歌词、词组切分
  alignment.json             # 保存的词级时间、字符位置、对齐分数
  prepare.py                 # 准备音频 → 对齐 → 生成预览
  align.py                   # 复用项目 MMS 强制对齐模型
  build.py                   # 将配置与时间轴生成静态预览
  serve.py                   # 本地预览服务；启动时重建页面
  render.py                  # 逐帧导出带原曲音频的 MP4
  verify.py                  # 浏览器功能检查
  requirements-preview.txt   # 视频导出 / 验证需要的额外依赖
  templates/                 # 场景框架、SVG 背景、播放控制页面及脚本
  data/                      # 原曲和 16 kHz 对齐用 WAV（不入 Git）
  preview/                   # 生成网页、片段音频、完整词组时间轴（不入 Git）
  exports/                   # 导出视频和验证截图（不入 Git）
```

Logo 始终从项目 `assets/adele-logo.png` 读取，不重新绘制。无需原聊天目录或 `work/lyrics-bubble/`。

## 重新生成有声对齐版

对齐复用项目 `.venv` 与根目录 `requirements.txt` 中的依赖，另需系统 `ffmpeg`。MMS 模型第一次运行可能下载权重；之后使用本机缓存。看已有预览只需要 Python 3，不需要模型、API 密钥或 Node。

使用已经下载的原曲：

```bash
.venv/bin/python lyrics_rolling_video/prepare.py
```

使用本地完整音频或视频文件：

```bash
.venv/bin/python lyrics_rolling_video/prepare.py --source "/绝对路径/歌曲.mp3"
```

`source_start` 是相对于该输入文件的秒数。若输入已经是截好的片段，应将配置中的起点改为 `0`；不要再次按完整歌曲的起点截取。

从 `config.json` 中的 YouTube 地址下载：

```bash
.venv/bin/python lyrics_rolling_video/prepare.py --download
```

如果 YouTube 要求登录验证，用户明确允许读取浏览器登录状态后，可执行：

```bash
.venv/bin/python lyrics_rolling_video/prepare.py --download --cookies-from-browser chrome
```

脚本不自动读取登录状态、不保存 Cookie 文件。音轨、下载缓存和生成预览留在本机，不入 Git。

处理步骤：

1. 按 `source_start`、`duration` 截取真实音频。
2. 生成 16 kHz 单声道 WAV 供对齐，另生成 48 kHz AAC 供浏览器试听。
3. 将**已校对的参考歌词**与音频用 MMS 强制对齐，得到每个词的起止时间与置信分数。
4. 按 `phrase_groups` 合并词组，保留真实停顿。
5. 用词组字符范围测量气泡位置和宽度，生成页面。

这份样片的原曲位置最初由项目的 Qwen ASR 定位。识别文字未作为歌词来源；当前固定片段的重建不需要再次调用 ASR，也不需要云端 API。换歌时需先核实片段起点和实际演唱文本，不能把错误歌词强制对齐后直接当成正确结果。

## 调整歌词、词组和画面

`config.json` 是编辑入口：

- `title`：目前为两行歌名；`title_zh`、`artist`、`language_label` 控制标题区。
- `source_url`、`source_start`、`duration`：原曲与片段范围。
- `lines`：每行 `fr` 为原文、`zh` 为译文；`fr` 是本法语样片沿用的字段名。
- `phrase_groups`：按行配置词索引区间 `[起点, 终点)`，从 0 开始。例如 `[[0,3],[3,5]]` 把一行前 3 个词和后 2 个词分成两个气泡。连字符会分词，带撇号的缩写保留在同一词内；以 `alignment.json` 的字符位置为准。

只改标题、译文以外的视觉参数或词组切分，可重新生成页面：

```bash
python3 lyrics_rolling_video/build.py
```

**修改 `lines`、片段起点或时长后重新执行 `prepare.py`。** 构建器会阻止把变化后的歌词与旧字符索引混用。只改译文时当前也需要重做对齐，以保持输入一致性。

画面参数在 `build.py`（字号、行距、颜色、气泡过渡约 110 ms）和 `templates/scene.html`（整页面板透视矩阵）中。播放器逻辑在 `templates/aligned-player.js`。不要直接编辑 `preview/`，重建会覆盖它。

当前是 **最多 10 行的一页片段原型**，没有整首歌曲的自动分页、任意长句自动换行、跨页滚动或全语言分词。长句目前在 `lines` 中手动断行，并对应切分译文；更改字体/字数后需检查溢出。自动对齐分数低、人名、快速连唱、和声等位置应重点试听。

## 动画由什么生成

浏览器用 SVG 排版文字、测量词组，JavaScript 按词组时间插值气泡的位置及宽度，CSS 对整个面板做透视投影。播放始终读取 `audio.currentTime`，不会用独立计时器模拟唱词。短音频先完整加载为 Blob，保证基础本地 HTTP 服务也能稳定跳转。

视频导出使用同一场景的 `drawAt(t)`，按帧时间渲染，再由 FFmpeg 合入音轨。无需游戏引擎。

## 导出 MP4

首次安装额外依赖（已有 Chrome 时无需下载 Playwright 浏览器）：

```bash
.venv/bin/pip install -r lyrics_rolling_video/requirements-preview.txt
```

生成当前样片的 1080 × 1920、30 fps 有声视频：

```bash
python3 lyrics_rolling_video/build.py
.venv/bin/python lyrics_rolling_video/render.py
```

输出在 `lyrics_rolling_video/exports/aligned-preview.mp4`。快速预览可用 `--width 720`；支持 `--fps 60`、`--output /路径/成片.mp4`。默认使用 macOS 的 Google Chrome，其他系统用 `--browser /路径/chrome` 指定浏览器。

## 验证与排错

启动服务后运行：

```bash
.venv/bin/python lyrics_rolling_video/verify.py --url http://127.0.0.1:8765/
```

检查真实音频播放、暂停、跳转到指定时间、气泡时钟同步、调速、偏移、词组边界、手机宽度布局和页面错误。截图写入 `exports/verification.png`。

- **播放按钮一直加载**：检查终端错误和片段音频是否存在；缺失时运行 `prepare.py`。
- **修改后看到旧页面**：刷新页面。本服务关闭了静态缓存。
- **没有声音**：点击播放，检查系统音量与浏览器静音设置；页面不会强制自动播放声音。
- **对齐不自然**：先确认输入版本、截取起点和参考歌词正确，再试听低分词。整体微调只能解决统一早晚，不能修复个别词的错误。
- **换设备后没有音频**：媒体按目录规则不入 Git，需要用本地源文件或授权下载重新准备。
