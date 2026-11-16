---
name: song-mv
description: 给一个歌曲视频链接（YouTube 等），产出 4K + 60帧插帧 + 水印 + 原文/中文双语歌词 + FLAC Hi-Res 的成品视频，以及 B 站投稿用的 16:9 / 4:3 封面和元数据 JSON。当用户给出歌曲链接并要求“做视频 / 出 4K60 / 加双语字幕 / 做封面 / 投稿信息”时使用。
---

# 单曲 4K60 双语视频流程

一律用 `.venv/bin/python` 运行；人声分离用 `.venv-sep`（make_mv 会自动调用）。安装见 README。
整场演唱会走 `python -m workflow.live`（方案见 docs/design/concert_pipeline.md），单曲按下面的顺序。

| 步骤 | 命令 | 产物 |
|---|---|---|
| 1. 下载、切片、歌词、人声分离 | `workflow/make_mv.py --name X --url "LINK" --to separate` | `posts/X/` 下 source.mp4、audio.flac、lyrics.txt、vocals.wav |
| 2. 投稿信息（标题、简介、标签） | `workflow/make_meta.py --name X --subtitle-langs "英语,中文" --note "演出名称、日期、场地"` | `posts/X/post/X.json` |
| 3. 字幕：对齐 / 观众合唱 / 讲话断句 / 翻译（直译 + 诗意版）/ 注释 | `-m workflow.song.run post X` | `posts/X/subs/`（lyrics_poetic.ass 是诗意版） |
| 3a. 独立标题翻译与校对 | `-m workflow.song.title_translation posts/X` | `title_translation.json`；同步字幕片头、投稿标题及审核草稿 |
| 4. 封面 | `workflow/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中英字幕"` | `posts/X/post/cover/` |
| 5. 挂到审核页（字幕预览版 + 封面 + 投稿信息） | `-m workflow.live.singles X` | 审核页「单曲」里多一首（按歌名合并，不影响其他单曲） |
| 6. **用户在审核页看完、确认后**才做 4K 成品 | `-m workflow.song.render post:X` | `posts/X/post/X 4K60FPS Sub-WaterMark.mp4` |

封面和简介都在 4K 之前出，和字幕预览版一起给用户看；字幕、翻译、注释的修改都写进这首的定稿表（zh_fixed.json / zh_notes.json），
不调模型重新生成字幕；用户确认之前不渲染。歌词有现成的（用户给的、OCR 抄下来的、官方简介里的）就事先放到 `posts/X/lyrics.txt`，
第 1 步会跳过 Genius。封面要队徽：`--extra-logo assets/crests/<队>.png`；原视频有频道台标：`--inpaint-static`。

第 6 步默认使用苹果 VideoToolbox HEVC/H.265 硬件编码（`hevc_hw`，35 Mbps，峰值 50 Mbps）；可用 `--enc x264` 或 `--enc h264_hw` 手动切换。

第 6 步会自己补水印计划（workflow/song/watermark.py）、调 make_mv 的 interp（原片已经是 60 帧就不插帧也不抽帧），
渲染 4K + 诗意版字幕 + 中间浮动水印 + 原样 FLAC，渲染完删帧。路径约定见 `workflow/paths.py`。

## 硬性要求
- **音轨必须是 FLAC 48kHz/24bit**（B 站 “Hi-Res无损” 标）。render 用 `-c:a copy`，渲染后自动检查，不符直接报错
- **字幕文字只来自参考歌词**（YouTube 官方带时间字幕，或 Genius 歌词文本）；识别结果（Qwen）只用来定位、复核；讲话行用识别文字
- **Claude 不自己写出或改写歌词、不从网页抓歌词贴进对话**：歌词由 `get_ytb_lyrics_from_link.py` 写进本地文件，或用户自己保存；汇报时只给句号、时间点、统计
- 投稿 JSON 里的事实必须有出处（视频简介、用户提供、可查证资料），生成后人工核对；标题 ≤ 80 字，简介 ≤ 2000 字（超了在歌词介绍中间按句号删句）
- 没有用户确认，不做切视频、插帧、加 logo / 水印

## 当前审核与竖屏规范

竖屏、实时预览、横屏参考和投稿封面统一遵循仓库根目录的 vertical_workflow.md，视觉参数读取 workflow/portrait_style.json，基准为已确认的 Dark Horse 版本。

- **预览、片头和单曲封面的显示文字**顺序为原文歌名、中文歌名翻译、英文歌手名；不显示中文歌手名。**B 站投稿标题**使用下文「投稿信息核对」的字段顺序，两者不能互相套用。中文艺名保留在投稿资料中。
- 预览与视频片头全部纯白字，歌名加粗黑描边，中英文歌词黑描边每侧 2px；竖封面下方第一行演出名称，第二行「中英字幕」，两行均为金色。配套 4:3 横封面使用相同文字规则。
- 中文字幕不带前后音乐符号。横屏字幕英文在上、中文在下，竖屏中文在上、英文在下。
- 横屏和竖屏预览、成片均不额外添加固定的朝阳 Adele logo，保留原片水印，浮动水印按原计划显示。
- 修改规范只更新工作流与实时预览，批量重新生成已有封面或成片按用户具体指令执行。

## 1. make_mv 参数
- `--name` 短名；`--start/--end` 截取（直播 / 合集）
- 视频有**官方人工字幕**（不是自动字幕）→ `--sub-lang ja` 用它作参考歌词；否则走 Genius（识别不准时 `--song-title/--artist` 或 `--genius-url`）。现场版歌词可能和录音室版不同，提醒用户过一眼
- 需要登录：`--cookies-from-browser chrome`（先征得用户同意）。YouTube 常变，先 `.venv/bin/pip install -U "yt-dlp[default]"`；下载最高 2160p、原声音轨

## 2. 封面（16:9 + 4:3）
副标题默认自然字距居中，不补字距撑满标题宽度；短文案可用 `--artist-zh` 补中文艺名，
封面第二行默认带场次 / 节目名称；MV 默认标注 `MV`。从已核对的演出信息读取名称，`--event` 可覆盖；放在字幕语言标签之前。
英文显示歌名统一标题大小写，原始歌词正文保留原文。

```bash
.venv/bin/python workflow/make_cover.py --name X --title "歌名" --subtitle "歌手 · 中日字幕"
.venv/bin/python workflow/make_cover.py --name X --title "Lose Yourself" --subtitle "Eminem · 中英字幕" --artist-zh "埃米纳姆" --event "奥斯卡2020"
.venv/bin/python workflow/make_cover.py --name X --title "歌名" --subtitle "..." --at 65.2 [--text-y 0.80]   # 指定帧
```
- 默认按正脸挑演唱者：正脸特写 `closeup_XX` / 半身 `half_XX` / 全身 `full_XX`，总览图 `candidates_*.jpg` 给用户挑；不够时 `--at` 指定时间补
- 每张同时出 16:9 `cover_XX.jpg` 和 4:3 `cover_XX_4x3.jpg`；画面两角有转播歌名 / 台标用 `--inpaint-corners`；专辑图等外部图 `--image ... --fill extend`
- 用户选定后改名为 `cover_01.jpg` / `cover_01_4x3.jpg`，`posts/X/post/cover/` 只留这两张

## 3. 投稿信息核对
标题译名统一读取 `title_translation.json`，`zh_fixed.json` 的 `__title__` 优先级最高。
标题步骤有独立缓存，可单独重跑；不再由通用片头翻译和歌词流程分别命名。
人工修订示例：`-m workflow.song.title_translation posts/X --title-zh "真正的痞子阿姆" --artist-zh "埃米纳姆"`。
这会重建字幕文字并同步本地投稿草稿，无需重新对齐或渲染视频；导出资料和线上标题仍需分别同步、回读核对。人物名和角色名应统一，
不要机械保留英文；意译不可宣称是官方译名。歌词中需要修订的句子另存 `zh_fixed.json`。

- B 站投稿标题顺序固定为：`歌手中文名 英文歌名 歌手中文昵称 歌手英文名 中文歌名 演出信息 关键词`。字段之间用空格，不插入点号，不自动加 `[4K60帧/Hi-Res]` 前缀。歌曲或艺名本身的标点保留。
- 昵称放在指定位置，不能代替开头的歌手中文名，也不重复堆叠中英文署名。中文名、中文歌名和演出信息应从已核对资料读取；缺少资料要列为待补，不能把英文占位当作中文资料完整。
- 多人合唱用首位歌手名加「等」，串烧用首曲完整歌名加「等串烧」，再套同一字段顺序；合唱一首歌不标成串烧。`Mumford & Sons` 等乐队名中的 `&` 属于名字，`U2乐队`、`HKT48组合` 的字母与数字也不能删掉。
- 总长最多 80 字符，**演唱会／节目名称是保留信息，不能因超长直接删除**。先从末尾整项移除通用关键词；仍超长时，依次减少昵称、使用已核对的较短演出名称、整项省略中文歌名译名，剩余字段仍按上述顺序排列。歌手、完整英文首曲名和演出信息仍放不下时，列为待人工简写，不自动截断或提交。不要硬截单词、歌名或演出名称，不为凑满 80 字符补词；整场演出名已包含在歌名字段中的，不重复添加。
- 标题格式共用 `workflow.bili_title`，不在生成、导出、换封面或投稿预检入口另写旧模板。人工填写的 `review.json` 标题优先，重导出不得覆盖。
- 单曲结构化标题资料优先读 `post/<name>.json`，无该文件的演唱会歌曲读 `post_draft.json`；不能让旧草稿或派生 JSON 覆盖新资料。通过 `workflow.delivery_bundle.write_bundle` 导出，并核对审核页、`post/bili_upload.json` 和投稿预检的最终标题一致。
- 「合集显示名称」单独保存为 `英文歌名 中文歌名`，只保留歌名，不带歌手、演出和关键词。合集名称采用 `英文歌手名称-年份-演唱会中文名称`；新建合集默认开启分组，按歌单顺序放入「正片」。合集封面读取审核页「合集信息和全部封面信息」里的专用合集封面。
- **生成后逐条核对并手改**：模型常把频道口号当演出细节、给罗马字人名乱配汉字、编造材料里没有的事实、用无依据的夸张；不写不确定的成员名字
- 简介只写歌和演出，不写视频制作（字幕收录了什么、画质处理等）

## 4. 投稿到 B 站
- `.venv/bin/python post_bili/upload.py posts/<name>` 只检查并打印要提交的内容；已有用户对当前批次的投稿授权时，检查通过后按授权执行 `--submit`；尚未授权时先展示具体资料供用户确认。
- 可见范围遵循用户选择；已要求公开的使用公开投稿。仅在用户选择自见试投时加 `--only-self`，不因流程调整擅自改成自见。
- 登录（`bin/biliup -u post_bili/cookies.json login`）要用户自己在终端扫码；细节见 post_bili/README.md
- 改生成代码不代表已有草稿、导出资料或线上稿件已更新。用户要求先审阅批量修改时，先提供 Excel 新旧对比和待补资料项，再按审阅结果同步；用户暂停或要求先审阅时，不继续线上批量修改。
- 线上修改按 BV 号和对应成片回执定位，不能只按标题认领。标题编辑走 `post_bili/edit_title.py`，保留完整简介、两种封面及视频 CID；接口的 250 字简介预览不能写回全文。保存后回读标题并核对其他字段，区分「已接受」与「已验证」，未核实的不能汇报为已完成。

## 存储默认规则
插帧、逐帧缓存与编码一律在内置磁盘完成，不逐帧转存外接盘。成片取得真实投稿回执后，复制到外接盘并校验大小及 SHA-256，再移除本地成片副本、保留原路径符号链接；原片与用户定稿不删除。空间不足时暂停并处理空间，不自动退回外接盘产帧。

## 投稿资料唯一来源与封面同步

按[投稿信息统一流程](../../docs/design/posting_content_flow.md)执行。演唱会的完整简介统一由
`workflow.live.package.draft_meta` 生成，不能把“文件已存在”的占位简介当完成。
派生 JSON 不作正文输入；结构化三部分与人工审核修改经
`workflow.delivery_bundle.write_bundle` 同步导出两平台。
更新封面仍调用该入口，完成后核对页面 API 与导出正文一致。
封面沿用项目 FIBO / reviewed_cover 流程，不自行替换生图引擎。
