# 演唱会封面问题汇总与改进方案

2026-11-10 · 封面与 4K 批量队列暂停期间的审查记录

## 统计范围

本轮累计 **49 条反馈案例**，包括上次记录的 39 条及本次补充的 10 条。同场同曲的多个缺点按首要返工原因计一次，其余保留在明细。不同版本各计一例；版本对应关系仍待确认时注明。比例反映反馈样本的构成，全库随机抽查另列。

## 问题出现比例与处理方式

| 首要问题 | 反馈案例 | 占 49 条 | 首选处理方式 |
|---|---:|---:|---|
| 主唱身份、主次或主体大小 | 16 | 32.7% | 按曲目署名和原片上下文定位主唱，合唱逐人标记。独唱优先主唱中近景，嘉宾场保留双方且主唱清楚，平权组合共同入画。缩至列表大小仍能认出指定人物才入选。 |
| 人物位置偏移 | 13 | 26.5% | 先在现有母图上逐比例平移、缩放，使面部脱离边缘、角标和底部文字；像素不足或没有裁切余量才换原帧。 |
| 角度不利辨认 | 6 | 12.2% | 回本曲选正面或自然三分之二侧面，放大核对眼睛和脸部轮廓；优先同一段演唱里的相邻镜头。 |
| 遮挡五官 | 4 | 8.2% | 原片话筒遮挡就换帧；后期角标或字遮挡先调画面。朝阳Adele 在上、4K 60 FPS 在下，整组固定左上。 |
| 新增或重复人物 | 3 | 6.1% | 对照原帧、模型实际输入和无字母图，标明是真人、舞台屏幕还是新增人物。原片自带抢镜投影就换镜头；生成新增则退回母图。 |
| 表情或姿态 | 3 | 6.1% | 围绕动作与表情连续看前后帧，选眼睛自然、肢体舒展、动作已完成的瞬间。优先换时刻，避免模型改造表情。 |
| 清晰度或选帧理由不足 | 3 | 6.1% | 模糊帧先从同曲挑清晰帧；仅反馈“偏弱”时并列三张不同镜头，对照表情、主体、动作和清晰度后定因。 |
| 封面缺失 | 1 | 2.0% | 核对参考帧、母图、四版文件与 UI 地址，定位中断步骤后补齐。 |

## 为什么母图会凭空出现乐手

《The Angel (North London Forever)》的实际模型输入对应原片 53.556 秒。暗红背景前只有戴帽主唱举手唱歌；母图左侧出现键盘手、右侧出现吉他手，还多了舞台灯架。变化在无字母图就已发生，排版只把这张母图复用到四种输出。可直接对照[模型输入](../../concerts/singles/songs/the_angel_hammersmith_5gu277dbf8i/covers/ai/references/fibo-7983c7eb3fb00316.png)和[无字母图](../../concerts/singles/songs/the_angel_hammersmith_5gu277dbf8i/covers/ai/master-ca63b20450ae.png)。

本次使用 FIBO 2.0 Edit Turbo，模板 concert-oil-v1，4 步推理。实际提示词明确要求保留表演人数，单曲补充句只描述机位、主体、表情、灯光和服装。流程把整幅参考图交给模型重绘，背景像素可以改变。一个可能的机制是模型把大片暗部重新解释为常见的现场乐队场景；这张对照不足以把原因归给步数、某个词或模型训练数据。静帧能证实新增了乐手，无法据此判定人物在跳舞。

### 另做一次全库随机抽查

从侧栏快照的 **397 个去重视频条目**中，不放回随机抽 24 个，各看一张本地母图及其登记的实际输入。为避免把暗处已有的人误判为新增，对疑似案例额外提亮参考图检查。保守标记 **7/24（29.2%）** 有清楚的新增背景人物。其余 17 张包含难判的远景、暗场和原片就有人的画面。29.2% 是这次抽样的明确标记比例；样本小，也未逐帧检查整场演出。它与上表的反馈占比使用不同分母。

## 流程改进与验收

1. **选帧先确认谁在唱。** 均匀抽帧容易漏掉短暂好镜头。先按镜头取样，再在优选镜头前后细采；每首保留三张有区别的候选。记录曲目版本、单曲时间、原片时间、主唱位置、合作成员和画面已有的投影。身份存疑时回看前后几秒及同场服装。清晰度、脸框和睁眼检测用于缩小候选范围，最终对照原片确认。
2. **生图前后逐区对照。** 将原帧、裁切／去台标后的实际输入、母图并排。按前景、后排和屏幕分别标记可辨人物。给简单背景写具体观察，例如“一名主唱，左右为空的暗红背景”。比较相同输入下的通用提示、具体场景提示及保留原背景的局部处理。固定种子与尺寸，记录新增人物、主唱变形、耗时和峰值内存。多画人物直接退回；反复失败时可采用原片加轻量非生成式风格处理，保住人物和背景。
3. **排版按四个最终输出验收。** B 站 16:9、B 站 4:3、抖音 3:4、抖音 4:3 分别检查。先叠上固定左上角的朝阳Adele 和 4K 60 FPS，以及底部实际歌名与署名，再调整画面。原图及列表缩略图各看一次，确认品牌、文字、眼睛和嘴没有相互遮挡。狭幅合唱可用主唱优质正面单人镜头；选择同框时须能辨认两位主唱。
4. **发布状态区分文件可用和视觉通过。** 现有接口核对四个文件、平台和尺寸。建议另外记录原帧审核、母图忠实度、四版视觉审核以及失败原因，绑定具体原帧、母图与排版版本。新候选全部通过才替换页面上的已选版本。

### 选帧时先看构图

在调用生图模型前，用本曲三个不同镜头做低成本试裁，排成三行四列。每行是一张原帧，每列是一种最终封面，叠加实际左上角标和标题占位，按 UI 列表宽度查看。

- **主体与面积**：先指出这首要呈现谁。在缩略图里能直接认出演唱者，表情和动作仍清楚。串烧优先找能交代主唱和现场动作的中近景；放大远景后脸部发糊就换镜头。
- **位置与留白**：独唱检查头部高度、视线方向与脸前留白。多人检查关键成员的分布、脸部大小，以及左右是否一侧过重或另一侧大面积空场。允许有意偏心，避免为追求几何对称裁掉成员。
- **角度与遮挡**：优先平视正面或自然三分之二侧面；检查最窄竖裁和固定左上角标是否切脸、挡眼。记录通过的裁切框和退回原因。四版均可排再选定参考帧进入生图。

### 队歌 MV 的构图

Andrew White《Forever Number One》的两个版本（`bayern_forever_drone`、`bayern_forever_number_one`）均以球队为主题。从各自 MV 原片选取可辨认拜仁的镜头，优先比较安联球场红色外立面、清楚的球场标识或看台全景。按场景主体选帧，允许零人入画。用四版缩略图检查建筑轮廓与标识是否完整，避开固定左上角标和底部歌名。原片中的球场字样属于场景识别信息；如果风格化会改错字或凭空补出歌手、球员、伴舞，优先采用原片调色排版。两个版本分别记录自己的参考帧与时间。

### 小批验证与全库修复顺序

先用《The Angel》测新增人物、《The Emptiness Machine》测指定主唱、《Oye Mi Amor》测嘉宾主次、《Nada》测左偏与固定角标、《La Tortura》测人物偏下、《Lose Yourself》测模糊。每首交付同屏对照和四版缩略图。小批通过条件是六首均能辨认主唱、母图无新增人物、四版均通过遮挡与构图复核。其后按已知问题处理这份清单，再审全库现有母图与参考图。先重排能靠裁切解决的，再为确需换帧或重绘的曲目调用模型。本文仅记录方案与审查结果，批量队列保持暂停。

## 逐曲反馈明细

| 场次或条目 | 曲名 | 首要问题 | 观察或待核事项 |
|---|---|---|---|
| Olivia · ACL | Vampire | 主唱身份、主次或主体大小 | 伴奏与主唱争夺前景 |
| Shakira · Madrid | Antología | 遮挡五官 | 角标曾挡住合唱者，复核单曲 1:20 附近的双人镜头 |
| Dua Lipa · Mexico | Oye Mi Amor | 主唱身份、主次或主体大小 | 嘉宾比 Dua 醒目 |
| 格莱美 2025 | Von Dutch / Guess | 主唱身份、主次或主体大小 | 主唱在缩略图中太小 |
| Lorde · Glastonbury 2025 | If She Could See Me Now | 人物位置偏移 | 靠右 |
| Lorde · Glastonbury 2025 | David | 人物位置偏移 | 靠右 |
| Lorde · Glastonbury 2025 | Broken Glass | 人物位置偏移 | 靠右 |
| Lorde · Glastonbury 2025 | Current Affairs | 遮挡五官 | 麦克风遮脸 |
| Olivia · 巴西 2025 | pretty isn’t pretty | 人物位置偏移 | 靠右 |
| Olivia · 巴西 2025 | love is embarrassing | 主唱身份、主次或主体大小 | 用户质疑主角身份，待原片对照 |
| Olivia · 巴西 2025 | bad idea right? | 人物位置偏移 | 靠左，右侧空场 |
| Olivia · Glastonbury 2025 | obsessed | 遮挡五官 | 人脸偏左，与品牌角标重叠 |
| Olivia · Glastonbury 2025 | good 4 u | 主唱身份、主次或主体大小 | 吉他手占据主体 |
| Olivia · Glastonbury 2025 | deja vu | 新增或重复人物 | 背景有重复的巨大主唱，来源待对照 |
| Olivia · Glastonbury 2025 | bad idea right? | 新增或重复人物 | 右后方重复主唱，来源待对照 |
| Olivia · Glastonbury 2025 | pretty isn’t pretty | 人物位置偏移 | 靠右 |
| Olivia · Glastonbury 2025 | happier | 人物位置偏移 | 主唱太靠下 |
| Dua Lipa · CBS 2024 | Levitating | 人物位置偏移 | 靠下 |
| Dua Lipa · CBS 2024 | Maria | 人物位置偏移 | 靠下 |
| Dua Lipa · CBS 2024 | Cold Heart | 主唱身份、主次或主体大小 | 嘉宾比主唱醒目 |
| 格莱美 2024 | Atomic City | 主唱身份、主次或主体大小 | 舞台全景，无法辨认表演者 |
| 格莱美 2024 | For Once in My Life 等串烧 | 主唱身份、主次或主体大小 | 看不出谁是主角，也缺清楚正脸 |
| Shakira · 黄金国 2019 | Nada | 人物位置偏移 | 主唱太靠左 |
| Shakira · 黄金国 2019 | Loca / Rabiosa | 表情或姿态 | 舞姿定格不自然，需看同一动作的前后帧 |
| Shakira · 黄金国 2019 | La Tortura | 人物位置偏移 | 主唱太靠下 |
| Shakira · 黄金国 2019 | Me Enamoré | 表情或姿态 | 动作过渡瞬间，肢体线条不舒展 |
| Eminem · Detroit 2002 | When the Music Stops | 表情或姿态 | 表情定格不佳 |
| Eminem · Detroit 2002 | Fight Music | 主唱身份、主次或主体大小 | 未看到主唱 |
| Adele · 版本待定位 | Rolling In the Deep | 角度不利辨认 | 脸转向后侧 |
| Adele · 版本待定位 | Set Fire To The Rain | 人物位置偏移 | 靠左，同时表情不够自然 |
| Ed Sheeran · 版本待定位 | Shape of You | 清晰度或选帧理由不足 | 只反馈选帧偏弱，需用候选对照明确原因 |
| Eminem · 单曲 | Lose Yourself | 清晰度或选帧理由不足 | 原帧模糊，同名多版本待定位 |
| Eminem · 单曲 | Rap God | 主唱身份、主次或主体大小 | 选到非主角，同名多版本待定位 |
| Eminem · 单曲 | Love the Way You Lie | 角度不利辨认 | 角度影响辨识度 |
| Eminem · 单曲 | Love the Way You Lie / Not Afraid | 主唱身份、主次或主体大小 | 主角太小 |
| Linkin Park · 单曲 | The Emptiness Machine | 主唱身份、主次或主体大小 | 没有选到用户指定的黄衣女主唱 |
| Lorde · 单曲 | Perfect Places | 角度不利辨认 | 不够正面，同名多版本待定位 |
| Lorde · 单曲 | Ribs | 角度不利辨认 | 不够正面 |
| Louis Dunford · Hammersmith | The Angel (North London Forever) | 新增或重复人物 | 原帧一人，母图新增左右两名乐手 |
| One Direction · VEVO LIFT | What Makes You Beautiful | 清晰度或选帧理由不足 | 原帧模糊且全员挤在左边，重选清晰、成员在画面两侧分布自然的组合镜头。 |
| Ricchi e Poveri · 疑似 1983 Popshow | Sarà perché ti amo | 角度不利辨认 | 现图可见明显侧面，优先重新找同框平视镜头。 |
| Ricchi e Poveri · 疑似圣雷莫 2020 | Sarà perché ti amo | 角度不利辨认 | 现图可见仰视侧面，换至接近眼平的机位。另有 2023 Zarrella 版，两条反馈的版本对应按画面初判。 |
| Shakira · Spotify Anniversary | Hips Don't Lie | 封面缺失 | 专辑接口没有封面地址，本地无四版成品；任务记录显示参考帧疑似闭眼。先重选这版的睁眼合唱帧，生成后验证四版和专辑入口。 |
| Shakira · 世界巡演，与 Wyclef 同台 | Hips Don't Lie | 主唱身份、主次或主体大小 | 已有封面以花衬衣嘉宾为前景，Shakira 偏小。换主唱突出、仍保留嘉宾的双人帧。 |
| Thelma Aoyama feat. SoulJa · THE FIRST TAKE | そばにいるね | 遮挡五官 | 左上品牌挡脸。叠加固定角标检查两位演唱者，调整裁切或换帧；库内另有 HKT48 版本。 |
| Zhasball · Erling Haaland Parody | I'm Humble Now | 主唱身份、主次或主体大小 | 用户指定蓝衣哈兰德为画面主角。人物角色写入选帧要求，对照原片确认，署名不能替代角色判断。 |
| 历届超级碗 · 2020 | 2020超级碗中场秀 | 主唱身份、主次或主体大小 | 用户反馈选错人。计划中有两位领衔者的姓名，仍需逐脸对照实际选帧，核对主唱与嘉宾。 |
| 历届超级碗 · Bruno Mars | Billionaire 等串烧 | 主唱身份、主次或主体大小 | 主体面积过小且角度不佳。优先平视中近景，缩小后能辨认 Bruno Mars，景别仍能交代表演动作。 |
| 历届超级碗 · 2022 | 2022超级碗中场秀 | 人物位置偏移 | 左右视觉重量失衡。按关键成员的位置、脸部大小和空舞台面积比较候选，横版与最窄竖版均须保持群像关系。 |

## 抽查复核索引

曲目目录与母图文件名可用于复核。抽样按侧栏实际曲目目录和歌曲标识排序，以 20261110 为随机种子洗牌取前 24 个。明确计入的样本标为“新增”；“未计入”不代表通过全套视觉审核。

| 序号 | 视频目录 | 本次母图 | 人物新增统计 |
|---:|---|---|---|
| 1 | shakira_madrid_2026/36_she_wolf | [输入](../../concerts/shakira_madrid_2026/songs/36_she_wolf/covers/ai/references/fibo-a737543ec76ba98e.png) · [母图](../../concerts/shakira_madrid_2026/songs/36_she_wolf/covers/ai/master-dc03fc496ec7.png) | 未计入 |
| 2 | lorde_acl2026/06_buzzcut_season | [输入](../../concerts/lorde_acl2026/songs/06_buzzcut_season/covers/ai/references/fibo-71ba65aee8938439.png) · [母图](../../concerts/lorde_acl2026/songs/06_buzzcut_season/covers/ai/master-9cc91922d1fa.png) | 未计入 |
| 3 | singles/hkt48_sobaniirune | [输入](../../concerts/singles/songs/hkt48_sobaniirune/covers/ai/references/fibo-84bb6c9e51785bda.png) · [母图](../../concerts/singles/songs/hkt48_sobaniirune/covers/ai/master-c568dcdfbaee.png) | 未计入 |
| 4 | grammys_2026/10_12_to_12 | [输入](../../concerts/grammys_2026/songs/10_12_to_12/covers/ai/references/fibo-48fbda9584bcc8a3.png) · [母图](../../concerts/grammys_2026/songs/10_12_to_12/covers/ai/master-81a34f1e16f2.png) | 新增 |
| 5 | grammys_2014/04_dark_horse | [输入](../../concerts/grammys_2014/songs/04_dark_horse/covers/ai/references/fibo-9fbf4728dd8a94cf.png) · [母图](../../concerts/grammys_2014/songs/04_dark_horse/covers/ai/master-cbb649af1909.png) | 未计入 |
| 6 | lorde_acl2026/14_supercut | [输入](../../concerts/lorde_acl2026/songs/14_supercut/covers/ai/references/fibo-d7fcd03b64fcf571.png) · [母图](../../concerts/lorde_acl2026/songs/14_supercut/covers/ai/master-1ee0f548b198.png) | 未计入 |
| 7 | shakira_el_dorado_2019/15_can_t_remember_to_forget_you | [输入](../../concerts/shakira_el_dorado_2019/songs/15_can_t_remember_to_forget_you/covers/ai/references/fibo-ac00b724457c92dc.png) · [母图](../../concerts/shakira_el_dorado_2019/songs/15_can_t_remember_to_forget_you/covers/ai/master-eb081841bcd2.png) | 未计入 |
| 8 | shakira_madrid_2026/16_copa_vacia | [输入](../../concerts/shakira_madrid_2026/songs/16_copa_vacia/covers/ai/references/fibo-260e17d634261b51.png) · [母图](../../concerts/shakira_madrid_2026/songs/16_copa_vacia/covers/ai/master-f5397564b2eb.png) | 新增 |
| 9 | eminem_detroit_anger_management/18_my_dad_s_gone_crazy | [输入](../../concerts/eminem_detroit_anger_management/songs/18_my_dad_s_gone_crazy/covers/ai/references/fibo-20b32815cd8733eb.png) · [母图](../../concerts/eminem_detroit_anger_management/songs/18_my_dad_s_gone_crazy/covers/ai/master-6a74eec0759b.png) | 未计入 |
| 10 | singles/ymca_1978 | [输入](../../concerts/singles/songs/ymca_1978/covers/ai/references/fibo-b6e4ca016b61b983.png) · [母图](../../concerts/singles/songs/ymca_1978/covers/ai/master-5606887f4b1d.png) | 未计入 |
| 11 | lorde_iheart_2017/04_liability | [输入](../../concerts/lorde_iheart_2017/songs/04_liability/covers/ai/references/fibo-75563e885cee507e.png) · [母图](../../concerts/lorde_iheart_2017/songs/04_liability/covers/ai/master-bcbf12da7d89.png) | 未计入 |
| 12 | olivia_lolla_brasil_2025/09_happier | [输入](../../concerts/olivia_lolla_brasil_2025/songs/09_happier/covers/ai/references/fibo-553ec2330eda2e38.png) · [母图](../../concerts/olivia_lolla_brasil_2025/songs/09_happier/covers/ai/master-5613aed1f0fb.png) | 未计入 |
| 13 | lorde_acl2026/11_oceanic_feeling | [输入](../../concerts/lorde_acl2026/songs/11_oceanic_feeling/covers/ai/references/fibo-a47be20a6b21cb2e.png) · [母图](../../concerts/lorde_acl2026/songs/11_oceanic_feeling/covers/ai/master-cb587e848629.png) | 未计入 |
| 14 | lorde_lolla_chile2026/04_buzzcut_season | [输入](../../concerts/lorde_lolla_chile2026/songs/04_buzzcut_season/covers/ai/references/fibo-d7f9f0ce0a251450.png) · [母图](../../concerts/lorde_lolla_chile2026/songs/04_buzzcut_season/covers/ai/master-fbebf4bafb44.png) | 新增 |
| 15 | lorde_glastonbury_2025/04_man_of_the_year | [输入](../../concerts/lorde_glastonbury_2025/songs/04_man_of_the_year/covers/ai/references/fibo-620067ae3c5dad81.png) · [母图](../../concerts/lorde_glastonbury_2025/songs/04_man_of_the_year/covers/ai/master-b133fdb02d61.png) | 未计入 |
| 16 | grammys_2026/18_so_far_ahead | [输入](../../concerts/grammys_2026/songs/18_so_far_ahead/covers/ai/references/fibo-6635355a6295099f.png) · [母图](../../concerts/grammys_2026/songs/18_so_far_ahead/covers/ai/master-a42b88f78e2e.png) | 未计入 |
| 17 | lorde_lolla_chile2026/15_what_was_that | [输入](../../concerts/lorde_lolla_chile2026/songs/15_what_was_that/covers/ai/references/fibo-1334607d5caa41a2.png) · [母图](../../concerts/lorde_lolla_chile2026/songs/15_what_was_that/covers/ai/master-e2199d4e7ae4.png) | 新增 |
| 18 | dualipa_mexico2025/19_new_rules | [输入](../../concerts/dualipa_mexico2025/songs/19_new_rules/covers/ai/references/fibo-782cd2121b3a6b46.png) · [母图](../../concerts/dualipa_mexico2025/songs/19_new_rules/covers/ai/master-beee7527996b.png) | 未计入 |
| 19 | grammys_2014/06_cop_car | [输入](../../concerts/grammys_2014/songs/06_cop_car/covers/ai/references/fibo-c1ce9a50ba02c271.png) · [母图](../../concerts/grammys_2014/songs/06_cop_car/covers/ai/master-809c8173fee0.png) | 未计入 |
| 20 | lorde_lolla_chile2026/02_royals | [输入](../../concerts/lorde_lolla_chile2026/songs/02_royals/covers/ai/references/fibo-e8c3710025237a1f.png) · [母图](../../concerts/lorde_lolla_chile2026/songs/02_royals/covers/ai/master-a7ff215dc6e2.png) | 未计入 |
| 21 | singles/queued_20261103_rjvzfoz8-o8 | [输入](../../concerts/singles/songs/queued_20261103_rjvzfoz8-o8/covers/ai/references/fibo-87a0cc5578aa1d18.png) · [母图](../../concerts/singles/songs/queued_20261103_rjvzfoz8-o8/covers/ai/master-5ee016e741e5.png) | 新增 |
| 22 | lorde_lolla_chile2026/12_man_of_the_year | [输入](../../concerts/lorde_lolla_chile2026/songs/12_man_of_the_year/covers/ai/references/fibo-3d7318975680bbe2.png) · [母图](../../concerts/lorde_lolla_chile2026/songs/12_man_of_the_year/covers/ai/master-3a19f7979564.png) | 新增 |
| 23 | olivia_acl_lclxvyamuce/11_the_cure | [输入](../../concerts/olivia_acl_lclxvyamuce/songs/11_the_cure/covers/ai/references/fibo-250e5e8ab16e05fc.png) · [母图](../../concerts/olivia_acl_lclxvyamuce/songs/11_the_cure/covers/ai/master-e55eab76bc2b.png) | 新增 |
| 24 | singles/eminem_love_way_lie_not_afraid_vmas2010 | [输入](../../concerts/singles/songs/eminem_love_way_lie_not_afraid_vmas2010/covers/ai/references/fibo-004a244be1bb3b01.png) · [母图](../../concerts/singles/songs/eminem_love_way_lie_not_afraid_vmas2010/covers/ai/master-93bbfd0609ae.png) | 未计入 |
