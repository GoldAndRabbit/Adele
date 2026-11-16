# Adele：歌曲与演唱会的标准制作工作流

视频下载／本地原片 → 演唱会拆分或单曲区间登记 → 字幕搜索匹配与翻译 → 投稿信息与审稿 → 预览 → AI封面 → 已确认版本的4K成品。

**唯一总入口：** `.venv/bin/python -m workflow.live`。详细命令、七个模块、双Mac分工和暂停续跑见 [标准工作流](docs/workflow.md)。本地与副机执行相同模块，每台一首，按歌曲独立接续，不再运行日期目录中的批次脚本。

投稿标题、简介、标签、封面填字及文件名的具体模板和对应代码见 [投稿文案与封面文字模板](docs/design/publication_templates.md)。审稿页、完整JSON和导出使用同一份最终资料，人工定稿优先。

## 常用命令

```bash
# 登记整场本地原片，也可 --kind single --url LINK 登记单曲
.venv/bin/python -m workflow.live new my_concert --source '/Volumes/harddisk_5T/source.mkv' --artist 'Artist' --artist-zh '歌手中文名' --title '中文演出名' --title-en 'Event 2026'
# 默认准备到封面；新内容等待审稿，不自动做成品或投稿
.venv/bin/python -m workflow.live run my_concert
.venv/bin/python -m workflow.live serve
# 已确认预览的成品制作，默认双Mac；--local 切换为本机
.venv/bin/python -m workflow.live run my_concert --from delivery --to delivery --confirmed
# 多场及单曲共用声明式队列
.venv/bin/python -u -m workflow.live run --batch posts/my_batch --from delivery --to delivery --confirmed
.venv/bin/python -m workflow.live pause posts/my_batch
# 恢复上述命令时加 --resume
```

默认只生成B站4K60，配置位于 `delivery_defaults.json`。单渠道使用苹果流式插帧、字幕水印合成与HEVC编码，不落地中间视频或帧图片；原生60fps跳过插帧。显式选择双渠道才共享母版。编码预设在 `workflow/encoding.py`，不再从旧成品脚本导入。

输入和最终产物放在 `harddisk_5T`，插帧与工作缓存放在各执行Mac的内置盘。副机完成后回传、核对并安装到外盘。已有合格成品复用；已确认队列不重新执行ASR、出图或额外内容听审。各阶段耗时、机器和产物路径写回正式记录。

## 代码与数据

- `workflow/live/__main__.py`：唯一命令入口；`live/pipeline.py`：唯一项目和批次编排；`live/stages.py`：七个模块的调用边界。
- `workflow/runtime.py`：机器占用、按首动态派工、暂停、摘要缓存与锁。
- `workflow/song/`：现场识别、对齐、讲话、翻译、注释、水印及按需边界修正。
- `workflow/covers.py`、`fibo_*`、`reviewed_cover.py`：正式封面流程及版本发布。
- `workflow/delivery.py`、`dual_platform.py`、`stream_delivery.py`：同一成品引擎与本地／SSH传输。
- `workflow/templates.py`、`bili_title.py`、`make_meta.py`、`delivery_bundle.py`：文案模板、生成和统一导出。
- `server/`、`web/`：审稿页；`post_bili/`：独立授权的投稿与线上资料编辑工具。
- `concerts/`、`posts/`、`work/`：外盘项目资料、曲目与运行状态，不存放可复用业务流程代码，不进Git。

旧双机调度、旧RIFE帧序列成品链和批次编排脚本已退出。源码可在重构前提交 `5c380b3` 找回，删除清单见 `docs/design/removed_legacy_scripts.json`。原片、人工定稿、成品及真实投稿回执保留。

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


## 测试

```bash
.venv/bin/python -m unittest discover -s tests
# 两秒合成素材验证真实苹果编码及副机回传；不会处理实际曲目
ADELE_MEDIA_SMOKE=1 ADELE_REMOTE_SMOKE=user@second-mac .venv/bin/python -m unittest tests.test_media_smoke
```

## 下载、存储与发布

YouTube 下载会话统一由 `workflow/youtube_download.py` 提供 PO Token、代理和Cookie配置，媒体与元数据使用同一套会话；通过标准 `source` 模块调用。原片校验音视频轨与时长后才登记。外盘挂载与UUID读取本机 `external_storage.json`，凭证及本机配置不入Git。

审稿页位于 http://127.0.0.1:8160 。制作完成仅同步投稿资料，不自动上传。B站发布工具见 [post_bili/README.md](post_bili/README.md)，显式授权后才提交；已有回执不重复投稿。

独立歌词气泡预览模块见 [lyrics_rolling_video/README.md](lyrics_rolling_video/README.md)，它不参与标准成品调度。
