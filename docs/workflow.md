# 标准工作流

所有项目使用 `.venv/bin/python -m workflow.live`。单曲和演唱会进入相同的七个模块；批次只保存 JSON 任务、状态与日志。底层媒体、字幕及封面工具保留为实现和诊断接口，不再组合另一套总流程。

## 模块与代码

| 模块 | 功能 | 实现 |
| --- | --- | --- |
| `source` | 视频下载或本地原片登记、轨道与音频准备 | `download`、`youtube_download`、`live.ingest` |
| `split` | 演唱会歌单与拆分；单曲登记指定区间 | `live.stages.split`、`live.setlist / lyrics / segment` |
| `subtitles` | 搜索参考歌词、现场识别匹配、讲话、翻译、水印计划 | `preparation`、`song.run / song_translation_workflow` |
| `posting` | 标题、简介、标签与审稿资料，统一导出 | `live.package`、`make_meta`、`bili_title`、`delivery_bundle` |
| `preview` | 浏览器预览及时间轴 | `preview`、`browser_library`、`portrait_browser` |
| `covers` | 本曲选帧、FIBO 母图、排版、复核发布与资料同步 | `covers`、`fibo_reference / fibo_concert`、`reviewed_cover` |
| `delivery` | 已确认版本的苹果插帧、合成编码及回传 | `delivery`、`dual_platform.encode_job`、`stream_delivery`、`dual_render` |

总编排仅在 `live.pipeline`。所有逐首重型任务共用 `runtime.HostPool`，每台一首，完成后领取下一首，允许跨场；本地与副机不会复制业务步骤。字幕副机执行分离与对齐后回传，成品副机执行相同编码引擎后回传。整场粗定位复用字幕轨或按窗口识别原音频，不先加载整场分离模型；分离在逐曲阶段执行。

## 登记输入

演唱会本地文件：

```bash
.venv/bin/python -m workflow.live new my_concert --source '/Volumes/harddisk_5T/source.mkv' --artist 'Artist' --artist-zh '歌手中文名' --title '2026年中文演出名' --title-en 'Event 2026' --date 2026-01-01
```

歌单使用 `concerts/my_concert/setlist.txt`，或登记 `--setlist-url` 后使用既有 setlist.fm API 配置。文件格式沿用 `歌名 | 参考原唱 | 备注`，过场标记和串烧规则不变。

单曲视频链接使用同一入口：

```bash
.venv/bin/python -m workflow.live new my_single --kind single --url 'https://www.youtube.com/watch?v=VIDEO_ID' --song-title 'Song Name' --artist 'Artist' --artist-zh '歌手中文名' --title '专辑名或中文节目名' --title-en 'Album or Event'
```

单曲也可用 `--source`；需要截取时登记 `--start 2 --end 240`，单位为秒。新单曲项目和演唱会项目共用曲目结构，历史 `singles` 虚拟场次继续可读，不强制搬动既有数据。

## 准备到审稿页

```bash
.venv/bin/python -m workflow.live run my_concert
.venv/bin/python -m workflow.live serve
```

`run` 默认执行 `source → split → subtitles → posting → preview → covers`，不自动进入成品或投稿。新封面完成视觉复核并发布后同步投稿信息；没有复核的版本停在待审状态，保留已有发布封面。`--auto-review` 运行既有视觉复核模块，不代表人工审稿通过。

只重跑指定模块和歌曲：

```bash
.venv/bin/python -m workflow.live run my_concert --from posting --to preview --songs 1,2
.venv/bin/python -m workflow.live run my_concert --from covers --to covers --songs 1 --replace-covers --auto-review
```

默认第二台 Mac、密钥路径、本机 FIBO 模型与副机 FIBO 配置路径读取 `delivery_defaults.json.worker`。`--local` 只用本机；`--remote user@host --key ~/.ssh/key` 显式指定副机。副机须已安装相应 GPU 环境与模型，失败不会静默改用 CPU。下载会话可使用 `--browser chrome --proxy http://127.0.0.1:7890`；Cookie 与 PO Token 沿用共享下载模块，不写进项目文案。

## 已确认预览的成品制作

```bash
.venv/bin/python -m workflow.live run my_concert --from delivery --to delivery --confirmed
```

`--confirmed` 表示用户已经确认这一批预览，直接复用字幕、封面和投稿资料。未指定时按正式审稿状态筛选。不会在成品阶段重新识别、重新翻译或自动做内容修复。

默认只出 B站 4K60，使用苹果流式路径：解码／插帧后的帧直接进入字幕水印合成与 HEVC 编码，不落地帧图片或 60fps 中间视频。原生 60fps 跳过插帧。明确需要双渠道时使用 `--platforms bilibili douyin`，才进入共享母版策略。编码预设唯一位于 `workflow/encoding.py`。

输入、最终产物在外盘；插帧及工作缓存位于执行 Mac 内置盘。副机编码在副机本地完成，回传及摘要核对后安装到主机外盘。日志记录执行机器、起止时间、准备、编码、传输等阶段耗时。

## 全量批次与暂停续跑

正式批次目录的 `queue.json` 示例：

```json
{
  "projects": [
    {"concert": "first_concert", "songs": ["01_first_song", "02_second_song"]},
    {"concert": "singles", "songs": ["existing_single_name"]}
  ],
  "remote": "user@second-mac",
  "render_platforms": ["bilibili"],
  "options": {"confirmed": true},
  "awaiting_user_review": [],
  "blocked_jobs": {}
}
```

历史 `concerts + priority_status.json` 队列由输入适配器读取，既有成品继续复用，无需跑旧脚本。

```bash
.venv/bin/python -m workflow.live run --batch posts/my_batch --from delivery --to delivery --dry-run
.venv/bin/python -u -m workflow.live run --batch posts/my_batch --from delivery --to delivery --confirmed
.venv/bin/python -m workflow.live pause posts/my_batch
.venv/bin/python -m workflow.live run --batch posts/my_batch --from delivery --to delivery --confirmed --resume
```

暂停停止领取新任务，当前一至两首收尾。恢复只处理剩余任务。调度器重启会接管存活的标准工作进程，单曲锁和机器锁防止重复运行；单首失败记录原因并让其他歌曲继续。失败不无限重试，修复后明确接续。

`workflow_status.json` 是批次当前状态，`jobs/<任务ID>/worker.log` 和 `result.json` 是逐首日志与耗时；`render_status.json / products.json` 是实际成品记录。导出及页面统一使用 `delivery_bundle`。

## 投稿与封面模板

具体字段、正文示例、优先级和代码位置见 [投稿文案与封面文字模板](/Users/gold/repos/adele/docs/design/publication_templates.md)。新封面发布或成品交付都更新投稿资料。B站和抖音资料按同一事实来源派生；制作不等于上传，发布仍由明确授权的投稿工具执行。

## 验证与历史代码

```bash
.venv/bin/python -m unittest discover -s tests
ADELE_MEDIA_SMOKE=1 ADELE_REMOTE_SMOKE=user@second-mac .venv/bin/python -m unittest tests.test_media_smoke
```

第二条仅使用合成的两秒素材，验证原生 60fps、30→60 插帧及 SSH 回传，不改变实际曲目。需真实 Mac GPU 和已配置 SSH 环境。

重构前源码保存在 `main` 的 `5c380b3`。旧批次脚本删除清单及摘要见 `docs/design/removed_legacy_scripts.json`，可用 `git show 5c380b3:legacy_batch_sources/<原路径>` 查阅。素材、人工定稿和历史回执不在删除范围。
