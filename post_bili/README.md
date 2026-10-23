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

```bash
# 1. 检查：不上传，只打印标题 / 简介 / 标签 / 封面 / 成品规格，有问题标 ✗
.venv/bin/python post_bili/upload.py posts/agua_madrid_official          # 单曲
.venv/bin/python post_bili/upload.py posts/lorde_acl2026/01_royals       # 演唱会里的一首

# 2. 看过没问题再加 --submit
.venv/bin/python post_bili/upload.py posts/agua_madrid_official --submit
```

常用选项：

| 选项 | 作用 |
|---|---|
| `--only-self` | 仅自己可见。第一次投或改了流程时用，先在 B 站上看实际效果，没问题再去创作中心改成公开 |
| `--at "2026-10-25 20:00"` | 定时发布（本机时间），至少晚于提交 4 小时，B 站规定 |
| `--source URL` | 转载来源，覆盖 JSON 里的 |
| `--cover 图片` | 换封面，覆盖审核页选的 |
| `--tid N` / `--tid-v2 N` | 投稿分区，默认见下面「投稿参数」 |
| `--types` | 查 B 站的分区表（要先登录），不用给歌曲目录 |
| `--line 线路` | 上传线路，默认自动选；传得慢可以换（`bin/biliup upload --help` 里有列表） |
| `--again` | 已经投过（有 `post/publish.json`）还要再投 |

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
| 封面（4:3） | — | 不提交 | biliup 不支持，需要的话去网页补 |
| 标题 | `title` | 投稿 JSON | make_meta.py / package.py |
| 类型 | `copyright` | 2 转载 | `DEFAULTS` |
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
| 互动视频 / 参加活动 | `interactive` / `mission_id` | 不用 | — |
| 空间动态 | `dynamic` | 空 | — |
| 精选评论 / 关评论 / 关弹幕 | `up_selection_reply` 等 | 都不开 | — |
| 字幕 | `subtitle` | 不传（字幕已经烧在画面里） | — |
| 合集 | — | 不加 | 网页或 `bin/biliup season add` |

有两项第一次试投后要在创作中心核对：
- **杜比**：B 站的杜比音效一般要求音轨本身是杜比格式，我们的音轨是 FLAC 立体声。勾上之后 B 站是忽略、拒绝还是正常标，要看第一次的结果。
- **水印**：`watermark` 是网页投稿接口的字段，biliup 默认走客户端接口，不确定会不会被采纳。不生效的话改走网页接口（biliup upload 的 `--submit web`，要在 upload.py 里加上），或者把创作中心「投稿设置」里的默认水印关掉。

## 提交前检查

有一项不过就不投：
- 标题 1~80 字，简介 1~2000 字
- 成品是 3840x2160、60 帧、FLAC 48kHz/24bit（B 站靠 FLAC 给 Hi-Res 无损标，换 AAC 就没有）
- 有转载来源、有封面
- 标签：超过 20 字的去掉，超过 12 个只留前 12 个，去掉的会打印出来

## 投完之后

- `post/publish.json`：稿件号（BV / av）、提交时间、提交的全部字段。有这个文件就不会重复投。
- `logs/publish_<时间>.log`：biliup 的完整输出，失败时先看这里。
- 投完先进审核，审核通过才算发布。状态可以用 `bin/biliup -u post_bili/cookies.json list --is-pubing` 查，
  或者 `show <BV号>` 看单个稿件。
- 4:3 封面、合集这几项 upload.py 不管，需要的话去创作中心网页补。
  合集也可以用 `bin/biliup -u post_bili/cookies.json season ...` 管，见 `season --help`。

## 注意

- biliup 不是 B 站官方工具，走的是网页 / 客户端的投稿接口。B 站改了接口可能暂时用不了，要等 biliup 更新。
  升级时改 `install.sh` 里的 `VERSION` 和 `SHA256`，先用 `--only-self` 投一首试过再正式用。
- 别短时间连着投很多：B 站会返回 601（上传太频繁）。一首一首投没问题。
- 投出去就是公开的（除非加了 `--only-self`）。让 Claude 代投时，它要先把检查输出给你看，你确认了才加 `--submit`。
