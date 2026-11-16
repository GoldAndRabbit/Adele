# 投稿文案与封面文字模板

本文件规定自动生成、审稿页、完整投稿 JSON 和导出共用的文案模板。模板字段与限制在 [workflow/templates.py](/Users/gold/repos/adele/workflow/templates.py)；B站标题预算、正文生成和封面排版分别由下列正式模块实现。人工定稿优先，模板更新不会直接改线上稿件或批量重做已有封面。

## 1. B站投稿标题

完整字段顺序：

```text
{歌手中文名} {英文／原文歌名} {歌手中文昵称} {歌手英文名} {中文歌名} {演出信息} {关键词}
```

字段之间使用一个空格，空字段直接省略。不会自动添加 `[4K60帧/Hi-Res]` 前缀、书名号或中间点。歌名、艺名本身的标点保留。

例如字段为「洛德、Royals、神婆／洛奶、Lorde、贵族、ACL Festival 2026」时，按顺序组合为：

```text
洛德 Royals 神婆 洛奶 Lorde 贵族 ACL Festival 2026 欧美现场 Billboard Grammy 中英字幕
```

实际结果还要经过 80 字符预算。关键词按 `欧美现场 → Billboard → Grammy → 中英字幕` 的顺序排列，超长时从末尾整项移除；基础字段仍放不下，再减少昵称、使用已有且核对过的较短演出名，最后整项省略中文歌名。保留完整英文首曲名、歌手和演出身份，不硬截单词，也不为凑满 80 字补词。

串烧把歌名字段压缩为 `{第一首完整原文歌名}等串烧`；多位歌手依照正式署名规则使用首位歌手加「等」。乐队名中的 `&` 不据此拆成多人。已在歌名中完整表达的演出身份不再追加一次。

| 规则 | 代码位置 |
| --- | --- |
| 固定字段顺序、默认关键词、字符限制 | `templates.BILI_TITLE_FIELDS / BILI_KEYWORDS / TITLE_MAX` |
| 多人、串烧、演出身份与整字段缩减 | [bili_title.build_title](/Users/gold/repos/adele/workflow/bili_title.py) |
| 从曲目资料、演出资料和中文译名取值 | `bili_title.for_post` |
| 人工标题优先、最终标题及合集歌名 | `bili_title.reviewed_title / apply_submission_names` |
| 投稿草稿调用标题模板 | [live.package.post_title](/Users/gold/repos/adele/workflow/live/package.py) |

人工填写的 `review.json.songs[歌名].title` 优先。`title_translation.json` 保存正式中文歌名，`zh_fixed.json.__title__` 是中文歌名人工定稿来源。生成器不各自另起一个译名。

## 2. B站简介正文

结构化存储模板：

```json
{
  "intro": {
    "song": "歌曲背景、发行与音乐风格、主题；只使用已核对材料。",
    "performance": "本次演出或MV的来源、日期、场地、形式，以及实际画面支持的造型和舞台表现。",
    "lyrics": "用中文解释歌词的故事、情绪推进、主副歌与桥段、意象、双关及文化背景。"
  }
}
```

导出为三部分之间空一行的连续正文：

```text
{intro.song}

{intro.performance}

{intro.lyrics}
```

这三句示意文字不是可交付简介。正式生成时总长含空行 **1800–2000 字符**，目标约 1900–1980。常见篇幅是歌曲与演出各约 500–600 字，歌词解读约 750–850 字，按材料实际分配。三部分均须完整，不用一句「某某演唱了某歌」占位。

生成器先写约 2300–2700 字符的完整初稿，再删除中间或末尾的完整句子；不足时补充材料支持的内容并去重，再按完整句子删减。删减保留歌曲、演出与歌词三部分，不截半句话。

文案只写歌曲和本次演出／MV。画质处理、字幕制作流程不写进正文；缺乏依据的成绩、嘉宾、制作人和日期不编写，视频发布日期与歌曲发行日期分别保存。歌词解读使用自己的话，不大段引用原词。

| 规则 | 代码位置 |
| --- | --- |
| 正文三部分、总字数与最低保留篇幅 | `templates.INTRO_SECTIONS / DESC_MIN / DESC_MAX / INTRO_FLOORS` |
| 内容提示词与结构化模型返回值 | [make_meta.SYSTEM_PROMPT](/Users/gold/repos/adele/workflow/make_meta.py) |
| 生成、补写、去重、按整句删减 | `make_meta.generate_intro / unique_intro / fit_intro` |
| 将歌曲事实、参考歌词、实际画面与本场信息填入 | `live.package.draft_meta` |
| 正文拼接、旧字段兼容 | [post_bili.upload.description](/Users/gold/repos/adele/post_bili/upload.py) |
| 人工简介优先，并同步两平台 | [delivery_bundle.submission_records](/Users/gold/repos/adele/workflow/delivery_bundle.py) |

三部分齐全时它们是正文来源；`intro_text` 只是旧格式兼容字段。人工审稿简介 `review.json...intro` 优先。已有 `bili_upload.json` 等导出文件不能反过来锁住旧占位正文。`templates.posting_issues` 检查实际导出的最终文案；人工修改不合规范时保留原文并标记待审，继续准备预览和封面，不把合格草稿冒认成合格投稿结果。已确认的成品制作不会重复执行这项文案检查。

## 3. 标签与抖音派生文案

B站标签最多 12 个，每个最多 20 字符，去重后由歌手、歌曲、演出、音乐类型和既定活动／字幕标签组成。填写真实相关词，不用不相关关键词凑数量。自动生成统一要求 12 个有效标签；已有完整简介而标签不足时，`make_meta.generate_tags` 只补标签，不重写简介。人工标签优先。

抖音有独立的 30 个 UTF-16 单元标题预算，不能直接复制 B站 80 字标题。其候选从原文歌名、中文歌手／昵称及演出信息组合并按完整字段缩减；具体短标题策略在 [vertical_post.submission](/Users/gold/repos/adele/workflow/vertical_post.py)。描述正文来自同一份最终 B站简介的首段，再附上最多 5 个完整话题，整体不超过 1000 个 UTF-16 单元。

两平台共用事实、中文译名和最终简介来源，按各自字段限制派生。B站单渠道制作不会因此多做一份抖音视频。

## 4. 封面填字来源与版式

封面文字通过确定性排版填入 AI 母图；图像模型生成无文字母图，不能让模型在画面里自由写歌名。封面文案不使用 B站长标题中的昵称和搜索关键词。

### 4.1 当前正式 AI 封面：四个比例共用紧凑文字模板

B站 16:9、B站 4:3、抖音 3:4 和抖音 4:3 **都调用 `ai_cover.branded_cover`**，包括竖版 3:4。当前填字顺序是：

```text
{本曲原文歌名；长串烧使用已确认的简写}
{歌手中文名 歌手英文名} · {中文演出简称／专辑名}
```

例如结构可以填为：

```text
Royals
洛德 Lorde · ACL音乐节2026
```

这两个例子只展示字段组合；演出名必须来自对应曲目的正式资料。左上角的品牌与4K徽章由固定图形资产叠加，不由图像模型写字。紧凑模板使用白字、深色描边、正常字距和安全边距；不同画幅改变裁切和排版尺寸，不另写一套文案。

`song.json.cover_subtitle` 明确指定时优先使用该副标题。一般演唱会署名保留本曲嘉宾；单曲的场次／专辑名读取正式 `header_labels`，不能继承虚拟场次的“单曲”二字。紧凑版不在署名行末重复添加字幕语言，不填投稿搜索关键词和昵称。

当前紧凑模板没有额外的中文歌名行。中文歌名仍统一存于译名记录，供投稿标题和预览使用；如要改为中英双歌名封面，应修改这一个模板与排版器，再按用户范围重新生成，不能在批次脚本里另拼一行。

模板代码为 `templates.compact_cover_text`；`ai_cover.branded_cover` 负责从正式资料取值，`make_cover.compact_credit_layout` 负责字号、换行、居中与底部安全区。

### 4.2 预览片头及保留的旧版封面布局

预览／片头按 `原文歌名 → 中文歌名 → 歌手署名 → 演出信息` 填入，署名读取预览的正式显示字段，可能包含已核对的中英文署名；样式参数在 `portrait_style.json`。它与投稿标题的字段顺序不同。

`vertical_cover.cover_image / wide_cover` 还保留了五行布局的绘制能力：原文歌名、中文歌名、英文歌手名、演出名、字幕标签，其中页脚为金色。这是保留的版式工具，**不是当前 FIBO 四比例封面的默认模板**。不能把这套旧布局的说明当作新 AI 封面已经填入中文歌名的证据。

### 4.3 对应代码

| 填充内容／排版 | 代码位置 |
| --- | --- |
| 当前四比例 AI 封面的标题与署名块 | [templates.compact_cover_text](/Users/gold/repos/adele/workflow/templates.py) |
| 演出名、歌手中文名与英文名的正式取值、人工覆盖 | [vertical_cover.header_labels / event_label](/Users/gold/repos/adele/workflow/vertical_cover.py) |
| 正式中文歌名、人工定稿优先级 | [song.title_translation.header_translation / resolved](/Users/gold/repos/adele/workflow/song/title_translation.py) |
| 原文歌名及多人／串烧简写、演唱会署名行 | `live.package.cover_title / compact_cover_title / subtitle_line` |
| 四比例 AI 封面将上述字段交给排版器 | [ai_cover.branded_cover](/Users/gold/repos/adele/workflow/ai_cover.py) |
| 四比例文字字号、换行、描边、居中与安全边距 | [make_cover.compact_credit_layout / compose](/Users/gold/repos/adele/workflow/make_cover.py) |
| 竖版填字及金色页脚；4:3 配套版式 | `vertical_cover.cover_image / wide_cover` |
| 视频片头文字顺序与参数；与封面长标题分开 | [portrait_header.draw_portrait_header](/Users/gold/repos/adele/workflow/portrait_header.py)、[portrait_style.json](/Users/gold/repos/adele/workflow/portrait_style.json) |

## 5. 封面路径命名与自动同步

页面名称固定为 `douyin 3x4封面路径`、`douyin 4x3封面路径`、`bili 4x3封面路径`、`bili 16x9封面路径`。对外文件名固定为：

```text
douyin_ai_3x4_yymmddhhmm.jpg
douyin_ai_4x3_yymmddhhmm.jpg
bili_ai_4x3_yymmddhhmm.jpg
bili_ai_16x9_yymmddhhmm.jpg
```

扩展名沿用实际文件格式，时间按上海时区；同一分钟的不同版本用父目录区分。实现位于 `templates.cover_filename / COVER_PATH_LABELS` 和 [posting_cover.cover_path](/Users/gold/repos/adele/workflow/posting_cover.py)。

新封面经 `reviewed_cover.publish` 发布后，通过 `sync_cover_release → write_bundle` 更新正式投稿路径；成品交付也调用 `write_bundle`。页面展示、完整投稿 JSON、复制内容和两平台导出通过 `submission_records` 读取同一份最终资料。
