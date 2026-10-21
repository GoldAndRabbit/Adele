# Adele：歌曲 / 演唱会视频 → 4K60 双语字幕成品

给一首歌的视频，或者一整场演唱会，产出 B 站投稿用的整套素材：4K60 成品视频（双语字幕 + logo / 水印 + FLAC Hi-Res）、
16:9 / 4:3 封面、投稿标题 / 简介 / 标签。演唱会先在审核网页上逐首人工审核，通过的才出 4K。

## 项目结构

```
adele/
├── workflow/                 所有代码
│   ├── make_mv.py              单曲：下载 → 截取 / 降采样 → 歌词 → 人声分离 → 插帧（--from/--to 分阶段）
│   ├── make_cover.py           候选封面（正脸特写 / 半身 / 全身，16:9 + 4:3）
│   ├── make_meta.py            投稿标题（≤80 字）/ 简介（≤2000 字）/ 标签
│   ├── get_ytb_lyrics_from_link.py   YouTube 链接 → Genius 歌词
│   ├── translate_ass.py        双语 ASS 样式、歌名翻译
│   ├── qwen_asr.py  refine_timing.py  acoustic.py  textnorm.py   识别 / MMS 强制对齐 / 读音
│   ├── separate_roformer.py    Mel-Band RoFormer 人声分离（.venv-sep）
│   ├── llm.py  paths.py
│   │
│   ├── live/                   整场演唱会流程（python -m workflow.live）
│   │   ├── __main__.py           new / run / serve / hd / status
│   │   ├── ingest  setlist  lyrics  separate  segment  refine  preview  package   各阶段
│   │   ├── music_edges.py        按伴奏起停切单曲边界
│   │   ├── cover_rank.py         候选封面排序（Qwen-VL）
│   │   ├── review.py  hd.py      审核状态 / 只对通过的歌出成品
│   │   ├── singles.py            把单曲挂到审核页（虚拟场次 singles）
│   │   └── text_match  asr_match  line_match  concert_align  gap_fill   对齐用的工具函数
│   │
│   └── song/                   每首歌的字幕和成品（演唱会和单曲共用）
│       ├── listen.py  align.py  run.py   多遍识别 → 整首对齐 → 锚点校准 → 讲话 / 时间（入口 run.py）
│       ├── song_crowd_workflow.py        观众合唱检测
│       ├── song_translation_workflow.py  初译 → 直译版 → 审校 → 诗意版 → 歌名
│       ├── song_note_workflow.py         顶部注释
│       ├── watermark.py  render.py       水印计划 / 4K60 成品
│       └── reslice.py                    改边界后字幕按整场时间重新分配
│
├── server/app.py             审核页后端（FastAPI，:8160）
├── web/                      审核页前端（纯 JS：app.js  subs.js  style.css）
├── tests/                    回归检查（审核时指出过的问题）
├── docs/design/              方案文档
├── skills/song-mv/           Claude Code skill（单曲流程说明）
├── assets/  bin/  models/    logo / 字体，rife / realesrgan，各模型权重
│
│  ── 以下是数据，不入 git ──
├── concerts/<场次>/     整场文件：source.mp4 audio.flac vocals.wav setlist.json segments.json review.json
│   └── songs/<歌名> ──→ 软链接到 posts/<场次>/<歌名>
└── posts/
    ├── <场次>/<歌名>/   演唱会里的一首（如 posts/lorde_acl2026/01_royals/）
    └── <歌名>/          单曲（和场次目录同一级）
        ├── audio.flac  vocals.wav  lyrics.txt  preview.mp4  watermark.json  post_draft.json
        ├── subs/          字幕结果：lines.json  lyrics.ass  lyrics_literal.ass（直译版）
        │                  lyrics_poetic.ass（诗意版，成品用）  translation/result.json
        ├── covers/        候选封面
        ├── reports/  logs/
        └── post/          成品：<歌名> 4K60FPS Sub-WaterMark.mp4、封面、投稿 json
```

## 数据流

```
 单曲 YouTube 链接                                   整场演唱会视频
       │                                                   │
 workflow/make_mv.py --to separate              python -m workflow.live run <场次>
 （下载 / 歌词 / 人声）                          ingest → setlist → lyrics → separate → segment
       │                                         （music_edges：按伴奏切边界）
 workflow/make_meta.py（投稿信息）                         │
       │                                         refine：每首切音频 + 720p 预览
       ▼                                                   │
       └──────────────────────┬────────────────────────────┘
                              ▼
               workflow/song/run.py：多遍识别 → 对齐 → 观众合唱 → 讲话
               workflow/song/song_translation_workflow.py：直译版 + 诗意版 + 注释
                              │  → posts/…/subs/
                              ▼
               workflow/live/package.py（演唱会）：候选封面 + 标题 / 简介 / 标签
                              │
                              ▼
               审核页 python -m workflow.live serve（http://127.0.0.1:8160）
               只看不改：修改走对话，改定稿表 zh_fixed.json 等
                              │  通过
                              ▼
               workflow/song/render.py：插帧 60fps（原片 60 帧则跳过）→ 4K + 诗意版字幕
                               + logo / 水印 + FLAC 48k/24bit
                              │
                              ▼
               posts/…/post/<歌名> 4K60FPS Sub-WaterMark.mp4
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

### 单曲

```bash
.venv/bin/python workflow/make_mv.py --name X --url "https://www.youtube.com/watch?v=..." --to separate
.venv/bin/python workflow/make_meta.py --name X --subtitle-langs "英语,中文" --note "演出名称、日期、场地"
.venv/bin/python -m workflow.song.run post X        # 字幕：对齐 / 观众合唱 / 翻译 / 注释 → posts/X/subs/
.venv/bin/python -m workflow.live.singles X        # 挂到审核页
.venv/bin/python -m workflow.song.render post:X     # 4K60 成品
.venv/bin/python workflow/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中英字幕"
```

视频自带官方人工字幕时加 `--sub-lang ja`，用它作参考歌词。单独取歌词：
`workflow/get_ytb_lyrics_from_link.py "YOUTUBE_URL" --name X [--genius-url ...]`。详细规则见 [skills/song-mv/SKILL.md](skills/song-mv/SKILL.md)。

### 整场演唱会

数据在 `concerts/<场次>/` 和 `posts/<场次>/`。方案见 [docs/design/concert_pipeline.md](docs/design/concert_pipeline.md)。

```bash
# 建场次（title-box：转播画面上歌名字幕的位置，有就填，定位最准）
.venv/bin/python -m workflow.live new shakira_madrid_2026 --source "~/Downloads/xxx.mkv" --artist Shakira \
    --date 2026-10-03 --city Madrid --venue "Estadio Shakira" --title-box 40,976,660,56 --cover-mask-bottom 0.12
# 歌单：.env 里有 SETLISTFM_API_KEY 时加 --setlist-url 自动拉取；否则手写 concerts/<场次>/setlist.txt
# 审核前的全部阶段（ingest setlist lyrics separate segment refine preview package），不出成品
.venv/bin/python -m workflow.live run shakira_madrid_2026
.venv/bin/python -m workflow.live run shakira_madrid_2026 --from refine --songs 8,9   # 只重跑某几首
# 按伴奏重切边界，字幕按整场时间重新分到各首（不重跑识别）
.venv/bin/python -m workflow.live.music_edges lorde_acl2026 --write
.venv/bin/python -m workflow.song.reslice lorde_acl2026 concerts/lorde_acl2026/reports/music_edges.json
# 审核网页
.venv/bin/python -m workflow.live serve
# 审核通过后出成品（只处理通过且之后没改过的歌）
.venv/bin/python -m workflow.live hd shakira_madrid_2026 --dry-run
.venv/bin/python -m workflow.live hd shakira_madrid_2026
```

## 测试

```bash
.venv/bin/python tests/regression_shakira.py          # 审核时指出过的问题，逐条检查现在的字幕
.venv/bin/python tests/regression_shakira.py 32_dai_dai
```
