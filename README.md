# Adele：歌曲视频 → 4K60 双语字幕成品

给一个 YouTube 歌曲链接，产出 B 站投稿用的整套素材：

- `posts/<name>/post/<name> 4K60FPS Sub-WaterMark.mp4`：3840×2160、60 帧（RIFE 插帧）、左上角水印、原文 + 中文双语字幕、FLAC 48kHz/24bit 音轨（B 站 Hi-Res 无损标）
- `posts/<name>/post/cover/cover_01.jpg`（16:9）、`cover_01_4x3.jpg`（4:3）
- `posts/<name>/post/<name>.json`：投稿标题、歌曲介绍、演出介绍、标签

详细规则和注意事项见 [skills/song-mv/SKILL.md](skills/song-mv/SKILL.md)。

## 目录

```
workflow/   所有脚本（入口 make_mv.py / make_cover.py / make_meta.py / get_ytb_lyrics_from_link.py；路径约定 paths.py）
skills/     Claude Code skill（.claude/skills/song-mv 是它的软链接）
assets/     水印 adele-logo.png、4K60 徽章
bin/        rife-ncnn-vulkan、realesrgan-ncnn-vulkan
models/     所有模型：rife-v4.6（插帧）、realesrgan/（封面高清化）、melband_roformer/（人声分离：权重 + mss 模型代码）、yunet/（封面选帧：人脸检测 + 识别）
tests/
posts/<name>/   一首歌一个目录（不入 git）
    lyrics.txt / official.srt   参考歌词（Genius / 官方带时间字幕）
    lyrics.srt → lyrics.ass     对齐后的原文字幕 → 双语字幕
    source.mp4 video_1080.mp4 audio.flac vocals.wav reports/ frames_*/ zh_cache.json …   中间文件
    logs/                       每次运行的日志（make_mv 自动写入）
    cover_art.png               （可选）做封面用的外部图片，如专辑图
    post/                       成品：<name> 4K60FPS Sub-WaterMark.mp4、<name>.json、cover/
```

## 安装

```bash
brew install ffmpeg
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 人声分离（Mel-Band RoFormer）单独一个环境
python3.12 -m venv .venv-sep && .venv-sep/bin/pip install -r requirements-sep.txt
git clone --depth 1 https://github.com/ZFTurbo/Music-Source-Separation-Training.git models/melband_roformer/mss
mkdir -p models/melband_roformer && curl -L -o models/melband_roformer/MelBandRoformer.ckpt \
  https://huggingface.co/KimberleyJSN/melbandroformer/resolve/main/MelBandRoformer.ckpt

# 封面选帧的人脸检测 / 识别（OpenCV YuNet + SFace）
mkdir -p models/yunet
curl -L -o models/yunet/face_detection_yunet_2023mar.onnx \
  https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx
curl -L -o models/yunet/face_recognition_sface_2021dec.onnx \
  https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx

cp .env.example .env   # 填 DEEPSEEK_API_KEY（翻译/元数据）、ALIYUN_BAILIAN_API_KEY（Qwen3-ASR）
```

`bin/realesrgan-ncnn-vulkan` 和 `models/realesrgan/realesrgan-x4plus.*`（封面高清化）不入库，需要自行放入；缺失时封面跳过高清化。

## 用法

```bash
# 一条命令跑完视频（Genius 歌词作参考）
.venv/bin/python workflow/make_mv.py --name X --url "https://www.youtube.com/watch?v=..." \
    --lang ja --title "《歌名》 歌手"

# 视频自带官方带时间字幕时，用它作参考（时间轴更准）
.venv/bin/python workflow/make_mv.py --name X --url "..." --lang ja --sub-lang ja --title "..."

# 封面、投稿信息
.venv/bin/python workflow/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中日字幕"   # 正脸特写/半身/全身各 4 张候选
.venv/bin/python workflow/make_meta.py --name X --subtitle-langs "日语,中文" --note "演出名称、日期、场地"
```

阶段：`download → prep → lyrics → separate → align → translate → interp → render`，可用 `--from` / `--to` 断点续跑。

### 单独取歌词

```bash
.venv/bin/python workflow/get_ytb_lyrics_from_link.py "YOUTUBE_URL" --name X
.venv/bin/python workflow/get_ytb_lyrics_from_link.py "YOUTUBE_URL" --genius-url "https://genius.com/..." --name X
```

自动识别歌名、歌手，在 Genius 找原版歌词，保存到 `posts/X/lyrics.txt`（默认去掉 `[Verse]` 等标签，`--keep-sections` 保留）。识别不准时用 `--title` / `--artist` 或 `--genius-url` 指定；已有文件默认不覆盖（`--overwrite`）。设置 `GENIUS_ACCESS_TOKEN` 可改用官方 API 搜索。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests
```
