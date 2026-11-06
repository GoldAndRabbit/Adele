# Adele：歌曲 / 演唱会视频 → 4K60 双语字幕成品

给一首歌的视频，或者一整场演唱会，产出 B 站投稿用的整套素材：4K60 成品视频（双语字幕 + logo / 水印 + FLAC Hi-Res）、
16:9 / 4:3 封面、投稿标题 / 简介 / 标签。演唱会先在审核网页上逐首人工审核，通过的才出 4K。

## 演唱会竖屏预览

完整流程、封面审核和首句前 0.5 秒截取见 [竖屏工作流](vertical_workflow.md)。

AI 封面默认遵循 [AI 封面选帧策略 v1](docs/design/ai_cover_frame_selection.md)：全曲粗扫、不同构图优先、横竖裁切复核，首轮三个参考各生成一张，选定构图后再调风格。接入与缓存规则见 [Seedream 试跑](docs/design/seedream_cover_trial.md)。

实时预览使用单曲原片，由浏览器绘制模糊背景、标题、字幕及下沿渐变，共用原片解码和音轨，不烧录预览文件。字体和颜色统一读取 `workflow/portrait_style.json`；当前片头为英文歌名、中文歌名、英文歌手、中文年份场次，字幕中英文均为纯白，备注为无描边荧光绿。

## 共享一次插帧的双平台成品

完整方案见 [双平台 60fps 工作流](dual_platform_60fps_workflow.md)。当前已验证入口针对 TS 1080i25：去隔行得到50fps，苹果质量优先插帧到60fps，共享母版分别合成 B站4K60、抖音1080p60。最终编码直接引用 `workflow.song.render` 的苹果 HEVC 默认参数，保留首句前0.5秒与完整演出尾段。结果位于字幕预览右侧「产物」，显示单次阶段耗时。

```bash
.venv/bin/python -m workflow.dual_platform grammys_2014 01_drunk_in_love
# 显式增加已检查的 AI 封面计划（凭据从进程环境读取）
.venv/bin/python -m workflow.dual_platform grammys_2014 01_drunk_in_love --covers-only --ai-cover-plan concerts/grammys_2014/songs/01_drunk_in_love/covers/ai/seedream-plan.json
```

AI 母图派生 B站16:9/4:3、抖音3:4/4:3，另保留抖音旧模板对照；失败不自动重试。`delivery_bundle.json` 汇总成品、投稿文案、AI候选及待处理事项。生成不代替人工选封面，也不自动发布。

## 竖屏歌词气泡预览

独立模块位于 [`lyrics_rolling_video/`](lyrics_rolling_video/README.md)，包含词级对齐、透视歌词气泡动画、本地有声预览和 MP4 导出。

```bash
python3 lyrics_rolling_video/serve.py
```

打开 http://127.0.0.1:8765/；首次准备音频、端口冲突和重新生成步骤见模块 README。

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
├── post_bili/               B 站投稿：upload.py（检查 → --submit 上传）、install.sh（装 bin/biliup），见 post_bili/README.md
├── server/app.py             审核页后端（FastAPI，:8160）
├── web/                      审核页前端（纯 JS：app.js  subs.js  style.css）
├── lyrics_rolling_video/     竖屏歌词气泡：对齐 / 本地预览 / MP4 导出，见该目录 README
├── tests/                    回归检查（审核时指出过的问题）
├── docs/design/              方案文档
├── skills/song-mv/           Claude Code skill（单曲流程说明）
├── assets/  bin/  models/    logo / 字体，rife / realesrgan / biliup，各模型权重
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
                              │
                              ▼
               post_bili/upload.py：检查 → 确认后 --submit 投到 B 站 → post/publish.json
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

# B 站投稿工具（bin/biliup）+ 扫码登录（凭证在 post_bili/cookies.json，不入库）
post_bili/install.sh
bin/biliup -u post_bili/cookies.json login
```

`bin/realesrgan-ncnn-vulkan` 和 `models/realesrgan/realesrgan-x4plus.*`（封面高清化）不入库，需要自行放入；缺失时封面跳过高清化。

## 用法

### 单曲

```bash
.venv/bin/python workflow/make_mv.py --name X --url "https://www.youtube.com/watch?v=..." --to separate
.venv/bin/python workflow/make_meta.py --name X --subtitle-langs "英语,中文" --note "演出名称、日期、场地"
.venv/bin/python -m workflow.song.run post X        # 字幕：对齐 / 观众合唱 / 翻译 / 注释 → posts/X/subs/
.venv/bin/python -m workflow.live.singles X        # 挂到审核页
.venv/bin/python -m workflow.song.render post:X     # 4K60 成品，默认苹果 HEVC 硬件编码（hevc_hw）
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

### 投稿到 B 站

```bash
.venv/bin/python post_bili/upload.py posts/X                 # 只检查、打印要提交的内容
.venv/bin/python post_bili/upload.py posts/X --only-self --submit   # 确认后上传（先仅自己可见）
```

演唱会的歌要先在 `concerts/<场次>/concert.json` 加 `source_url`（转载来源）。详见 [post_bili/README.md](post_bili/README.md)。

## 测试

```bash
.venv/bin/python tests/regression_shakira.py          # 审核时指出过的问题，逐条检查现在的字幕
.venv/bin/python tests/regression_shakira.py 32_dai_dai
```

### 外接工作盘

本机通过 `external_storage.json` 配置归档目录。`processing: local` 使新单曲的工作目录保留在内置盘。
工作盘未挂载或只读时会报错，避免把外接目录误写回内置磁盘。迁移已有作业应在其未运行时复制、校验后切换软链接。
本机归档盘为 `harddisk_5T`，输入素材和成片存入 `/Volumes/harddisk_5T/adele-workflow`。抽帧、插帧、临时文件和编码使用内置盘。归档前校验卷 UUID，复制并校验文件后才替换本地路径。

### YouTube 原片下载

音乐视频下载和补源统一使用 `workflow/youtube_download.py`。下载前检查本机 bgutil 的 `/ping` 和插件版本，必要时启动服务。多个任务共用同一服务。视频和元数据查询使用同一组播放器客户端（`default,mweb`）、代理和指定的浏览器会话。PO Token 由插件按请求获取，不写入项目配置。

本机服务入口默认是 `../SubDub/tools/bgutil-pot/server/build/main.js`，可用 `ADELE_BGUTIL_SERVER_DIR` 指向另一份已编译、版本与插件一致的 server 目录。需要 Node；启动时只监听本机 4416 端口。重启电脑后，下一次下载会重新检查并按需拉起服务。

仅下载原片（使用本机代理和已授权的 Chrome 会话）：

```sh
.venv/bin/python workflow/make_mv.py --name SONG --url 'YOUTUBE_URL' --to download --proxy http://127.0.0.1:7890 --cookies-from-browser chrome
```

新增补源脚本应通过 `cli_args(url, proxy=..., browser=...)` 构建会话参数，媒体输出、断点和校验由调用方管理。Python 版 yt-dlp 可使用同模块的 `extractor_options(url)`。服务健康只表示本机提供器可用；统计完成数仍以实际下载的音轨、视频轨和时长为准。
