# post_bili：成品投稿到 B 站

把 `posts/` 下做好的一首歌（成品视频 + 审核页选的封面 + 投稿 JSON）用命令行投到 B 站。
上传工具是开源的 [biliup](https://github.com/biliup/biliup) 命令行版，单个可执行文件，装在 `bin/biliup`。

```
post_bili/
├── install.sh     下载固定版本的 biliup 到 bin/biliup，校验 sha256
├── upload.py      读投稿 JSON → 检查 → 打印要提交的内容 → 加 --submit 才上传
├── README.md
└── cookies.json   登录凭证（登录后生成，不入 git）
```

## 安装和登录（一次）

```bash
post_bili/install.sh                          # → bin/biliup（当前固定 v1.2.11）
bin/biliup -u post_bili/cookies.json login    # 选扫码登录，用 B 站 App 扫
```

`login` 要在终端里交互选择登录方式，得自己在终端里跑。登录会过期，过期后上传会报未登录，
可以先 `bin/biliup -u post_bili/cookies.json renew` 刷新，不行就重新 `login`。

`cookies.json` 等于账号密码：只放在本机，已经写进 `.gitignore`，不要发给别人，也不要拷到别处。

## 投一首

分两步，中间只看一个完整的投稿 JSON：`post/bili_upload.json`（审核页「投稿信息」里显示的就是它）。

```bash
# 1. 生成：从投稿草稿 + 成品 + 审核页选的封面拼出 post/bili_upload.json，并检查；不上传
.venv/bin/python post_bili/upload.py posts/dualipa_mexico2025/06_levitating
# 2. 看过 JSON 没问题再上传：只读 bili_upload.json，原样提交
.venv/bin/python post_bili/upload.py posts/dualipa_mexico2025/06_levitating --submit
```

已经有 `bili_upload.json` 时第 1 步不覆盖（可能手改过），按草稿重新生成加 `--rebuild`。

`bili_upload.json` 的 key 是 B 站投稿页上的名称，值也是投稿页上的说法，要改哪项直接改这个文件：

```json
{
  "视频文件": "posts/<场次>/<歌>/post/<歌> 4K60FPS Sub-WaterMark.mp4",
  "封面": "posts/<场次>/<歌>/post/<歌>_cover_picked_<时间>.png",
  "标题": "…（1~80 字）",
  "类型": "自制",            // 默认自制；改为转载时必须填转载来源
  "转载来源": "",
  "分区": 29,                // 音乐 > 音乐现场（旧版分区号）
  "新版分区": null,          // 登录后 --types 查；null 不提交
  "话题": "音乐分享官",      // 投稿页带 # 的蓝色话题（只能点选），话题名也要在标签里
  "话题ID": 3878,
  "活动ID": 4072303,         // 话题挂着的活动；换话题用 --topics 关键词 查
  "标签": ["…"],             // 最多 12 个，每个不超过 20 字
  "简介": "…（1~2000 字）",
  "定时发布": "",            // "YYYY-MM-DD HH:MM"，空 = 审核通过后立即；至少晚于提交 4 小时
  "可见范围": "公开",        // 公开 / 仅自己可见
  "Hi-Res无损": true,
  "杜比音效": true,
  "UP主水印": false,
  "禁止转载": false,
  "充电": false
}
```

生成时的选项（写进 JSON；上传时只看 JSON）：

| 选项 | 作用 |
|---|---|
| `--only-self` | 可见范围写「仅自己可见」 |
| `--at "2026-10-25 20:00"` | 定时发布（本机时间） |
| `--source URL` | 转载来源，覆盖投稿草稿里的 |
| `--cover 图片` | 换封面，覆盖审核页选的 |
| `--tid N` / `--tid-v2 N` | 投稿分区 |
| `--rebuild` | 已有 bili_upload.json 也按草稿重新生成 |

其他：`--types` 查 B 站的分区表（要先登录）；`--topics 关键词` 查话题的话题ID / 活动ID（如「音乐4K计划」话题ID 1285415、活动ID 4072080）；`--line 线路` 换上传线路；`--again` 已经投过（有 `post/publish.json`）还要再投。

## upload.py 读什么、查什么

| 内容 | 单曲 `posts/<名>/` | 演唱会 `posts/<场次>/<歌>/` |
|---|---|---|
| 标题 / 标签 | `post/<名>.json`（make_meta.py） | `post_draft.json`（live/package.py） |
| 简介 | 同上，歌曲 / 演出 / 歌词三段介绍用空行连起来 | 同上的 `intro_text` |
| 转载来源 | `source.url`（原 YouTube 链接） | `concerts/<场次>/concert.json` 的 `source_url`，**要手动加** |
| 成品 | `post/<名> 4K60FPS Sub-WaterMark.mp4` | 同左 |
| 封面 | 审核页选的 `post/<名>_cover_picked_<时间>.png`，有多张取最新的 | 同左 |

## 投稿参数

B 站投稿页上的每一项、我们的默认值和来源。固定选项集中在 `upload.py` 顶部的 `DEFAULTS`，要改默认就改那里。

| 投稿页上的名字 | 接口字段 | 我们的默认 | 来源 / 怎么改 |
|---|---|---|---|
| 视频文件 | — | `post/<名> 4K60FPS Sub-WaterMark.mp4` | render.py 的成品 |
| 封面（16:9） | `cover` | 审核页选的最新一张 | `--cover` |
| 封面（4:3） | `cover43` | 审核页选的最新一张 | biliup 没有参数：upload.py 先用网页传封面的接口传上去，地址走 `--extra-fields`（第一次投后在创作中心核对） |
| 标题 | `title` | 投稿 JSON | make_meta.py / package.py |
| 类型 | `copyright` | 1 自制 | `DEFAULTS` |
| 转载来源 | `source` | 原视频链接 | `--source` |
| 分区 | `tid` | 29（音乐 > 音乐现场） | `DEFAULTS` / `--tid` |
| 新版分区 | `tid_v2` | 不提交 | 登录后 `--types` 查「音乐」的号填进 `DEFAULTS` / `--tid-v2` |
| 标签 | `tag` | 投稿 JSON，≤12 个、每个 ≤20 字 | make_meta.py / package.py |
| 简介 | `desc` | 投稿 JSON，≤2000 字 | make_meta.py / package.py |
| 定时发布 | `dtime` | 不定时，审核过了就发 | `--at` |
| 可见范围 | `is_only_self` | 公开 | `--only-self` |
| Hi-Res 无损 | `lossless_music` | **开** | `DEFAULTS` |
| 杜比音效 | `dolby` | **开** | `DEFAULTS` |
| UP 主水印 | `watermark.state` | **不加** | `DEFAULTS`（biliup 没有单独参数，走 `--extra-fields`） |
| 禁止转载 | `no_reprint` | 关（转载稿不适用） | `DEFAULTS` |
| 充电 | `charging_pay` | 关 | `DEFAULTS` |
| 参与话题 / 活动 | `topic_id` + `topic_detail` / `mission_id` | 音乐分享官（3878 / 4072303） | `DEFAULTS`；网页接口字段，biliup 没有话题参数，走 `--extra-fields` |
| 互动视频 | `interactive` | 不用 | — |
| 空间动态 | `dynamic` | 空 | — |
| 精选评论 / 关评论 / 关弹幕 | `up_selection_reply` 等 | 都不开 | — |
| 字幕 | `subtitle` | 不传（字幕已经烧在画面里） | — |
| 合集 | — | 不加 | 网页或 `bin/biliup season add` |

有两项第一次试投后要在创作中心核对：
- **杜比**：B 站的杜比音效一般要求音轨本身是杜比格式，我们的音轨是 FLAC 立体声。勾上之后 B 站是忽略、拒绝还是正常标，要看第一次的结果。
- **水印、4:3 封面**：`watermark`、`cover43` 都是网页投稿接口的字段，upload.py 用 `--submit web` 走网页接口提交。不生效的话水印去创作中心「投稿设置」里关默认水印，4:3 封面去网页补。

## 提交前检查

有一项不过就不投：
- 标题 1~80 字，简介 1~2000 字
- 成品是 3840x2160、60 帧、FLAC 48kHz/24bit（B 站靠 FLAC 给 Hi-Res 无损标，换 AAC 就没有）
- 有 16:9 / 4:3 封面；类型选「转载」时必须有转载来源
- 标签：超过 20 字的去掉，超过 12 个只留前 12 个，去掉的会打印出来

## 投完之后

- `post/publish.json`：稿件号（BV / av）、提交时间、提交字段及成片版本。只有回执对应当前成片才跳过；旧成片回执保留到 `post/publish-history/`，不抵扣新版本上传。新回执记录实际文件路径、大小、修改时间、制作批次及成品清单中的 SHA256。
- `logs/publish_<时间>.log`：biliup 的完整输出，失败时先看这里。
- 投完先进审核，审核通过才算发布。状态可以用 `bin/biliup -u post_bili/cookies.json list --is-pubing` 查，
  或者 `show <BV号>` 看单个稿件。
- 合集 upload.py 不管，需要的话去创作中心网页补。
  合集也可以用 `bin/biliup -u post_bili/cookies.json season ...` 管，见 `season --help`。

## 注意

- biliup 不是 B 站官方工具，走的是网页 / 客户端的投稿接口。B 站改了接口可能暂时用不了，要等 biliup 更新。
  升级时改 `install.sh` 里的 `VERSION` 和 `SHA256`，先用 `--only-self` 投一首试过再正式用。
- 别短时间连着投很多：B 站会返回 601（上传太频繁）。一首一首投没问题。
- 投出去就是公开的（除非加了 `--only-self`）。让 Claude 代投时，它要先把检查输出给你看，你确认了才加 `--submit`。

## 按演出歌单批量投稿

用歌单序号多选，或用 `--all` 选择全部歌曲。按歌单顺序为每首成品提交独立稿件，再按该顺序追加到合集小节。只有当前成片版本的投稿回执可以复用稿件号；同名旧稿不能复用。默认只做本地检查。

```bash
.venv/bin/python post_bili/batch.py an_audience_with_adele_2021 --songs 1 2 4
.venv/bin/python post_bili/batch.py an_audience_with_adele_2021 --songs 1 2 4 --season 合集ID --submit
```

默认开启分组，按歌单顺序加入「正片」。投稿标题按「歌手中文名 英文歌名 歌手中文昵称 歌手英文名 中文歌名 演出信息 关键词」排列，字段之间使用空格，不插入点号。多人署名和串烧先简化为首位歌手等、首曲完整名称等串烧，再使用同一字段顺序。最多80字符，演唱会／节目名称必须保留。超出时先从末尾逐项删除通用关键词，再减少昵称、改用已核对的较短演出名称，最后才整项省略中文歌名译名；不硬截字、不要求凑到78–80字。歌手、完整英文首曲名和演出信息仍放不下时，列为待人工简写，不能自动省略演出信息；歌名字段已包含整场演出名时不重复添加。人工审核标题优先，导出、换封面和投稿预检不得重新生成覆盖。合集单集使用投稿信息中的「合集显示名称」，例如「Hello 你好」。指定其他小节时加 `--section 小节ID`。如果加入合集失败，重新运行会从已有投稿回执继续。
省略 --season 并加 --submit 时，按「英文歌手-年份-演唱会中文名称」复用或新建合集，每批创建或复用合集时，重新读取审核页「合集信息和全部封面信息」中的标题、简介和专用合集封面，并回读平台封面地址核对。该面板是合集封面的来源。

全库队列 `post_bili/full_library.py` 每首每轮尝试一次。单条预检或提交失败时保留异常和不确定提交标记，继续下一首及后续批次；不等审核通过，也不在失败条目上睡眠重试。所有可投新成品尝试后，再集中核对待定回执；确认未提交的条目下一轮补投。缺少当前成片回执的批次不标记合集完成。
已完成合集的封面维护放到本轮新稿尝试和待定回执核对之后；仅审核页合集资料发生变化时重新同步，成功后才保存来源快照。封面接口返回 `-702` 时延后剩余封面维护，不中断队列或回执核对。可用 `--reconcile-only` 单独核对待定回执，明确记载的旧版 BV 不参与新成品认领。旧版投稿资料没有话题、话题ID、活动ID时，按未选择活动读取，保留审核过的标题、简介和封面。
全库队列默认走 `bda2`，可用 `--line bldsa` 等 biliup 支持的线路切换上传节点。切换前仍需确认上一尝试未提交；列表查询失败时保留不确定标记，只有具体上传阶段的日志证据才能确认尚未到达稿件提交。

编辑线上稿件时，创作中心查询接口中的 `archive.desc` 可能只有 250 字预览，不能把它当作完整简介写回。修改标题也须从公开稿件接口取得完整简介，或使用对应版本的原始投稿回执核对；完整正文同时传入 `desc` 和 `desc_v2`，保存后通过公开接口核对全文。`post_bili/edit_description.py` 区分编辑已接受与全文已验证，保留当前标题、封面和视频 CID。

本次 378 条标题同步由 `post_bili/sync_titles.py` 按审批清单和当前成片回执绑定执行，历史版本不计入目标。只改标题，保留编辑前的完整简介、16:9 与 4:3 封面及视频 CID；已有相同标题且未发送编辑请求的，可通过创作中心清单核验。已提交的先回读，不重复发送。请求默认间隔至少 1.2 秒，遇到 `-702` 或 HTTP 412 即停止本轮请求；网页明确提示风险限制时停止自动重试，保存断点，待平台恢复后继续。不能用只有 250 字简介、缺少 4:3 封面的备用查询结果拼装编辑请求。

本次续改按用户要求走 `post_bili/title_tick.py`：每次触发最多处理一首，完成后至少间隔 60 秒，首内请求仍按低频发送。定时触发不能绕过 `pacing.json` 中的下一次允许时间；风控后冷却 30 分钟，期间不请求平台，也不恢复批量连续推进。《maggots for brains》的专辑归属纠错是用户另行授权的单曲简介修改，独立记录并优先处理，该次不再同时改下一首标题。全部标题及该项纠错完成后停用对应续改任务。

执行与汇报分别计时：`post_bili/title_queue.py --start` 启动唯一后台队列，按 `pacing.json` 逐首调用 `title_tick.py`，正常情况下每首完成后等待至少 60 秒。平台冷却和保护校验不能由汇报触发绕过。聊天定时任务每 20 分钟读取进度并汇报、检查后台队列是否仍在运行，不再每分钟生成聊天汇报；不要把20分钟汇报间隔用于暂停正常逐首执行。
