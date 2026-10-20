# v4 成品流程和进度（2026-10-20）

## 定下来的规则

- 成品统一用 v4 字幕（`workflow_v4/`），不再逐首挑 v3 / v4。v4 = v3 + 观众合唱检测，见 [v4_crowd_detection.md](v4_crowd_detection.md)。
- 原文没变的句子，中文沿用 v3（审过的）；只有对齐真变了的句子用 v4 新翻的。
- 和 v3 有任何一行不一样的歌，先不渲染，等人看；完全一样的直接出成品。
- 一首做完（删帧）再做下一首；同一时间只开一个本地模型。

## 每首的流程（`workflow_v4/render.py`）

```
没有 exp_v4 → 拷 v3 的翻译缓存 → 跑 v4 → 原文没变的句子中文沿用 v3 → 和 v3 逐行比对（reports/v4_vs_v3.txt）
  → （--hold-changed：有不一样的先不渲染，记到 concerts/render_v4_hold.json）
  → 磁盘预检
  → make_mv.py --from interp --to interp：从整场视频切 1080p → RIFE 插帧到 60fps
  → 渲染：4K（3840×2160）+ exp_v4/lyrics_zh2.ass（中文 v2，整体提前 0.8 s，和审核页默认一致）
          + 左上角 logo + 中间水印（watermark.json，和审核页预览同样的时间 / 位置 / 透明度 / 淡入淡出 / 阴影）
          + FLAC 48kHz/24bit 原样（渲染完检查，B 站 Hi-Res 无损）
  → 删 frames_out、video_1080.mp4
```

成品：`<歌曲目录>/post/<name> 4K60FPS Sub-WaterMark v4.mp4`（不覆盖旧版成品）。审核页预览下方直接播，带本机完整路径、
「复制路径」「在 Finder 中显示」。

```
.venv/bin/python -m workflow_v4.render song:shakira_madrid_2026:37_bzrp_music_sessions_53 post:lose_yourself_2009
.venv/bin/python -m workflow_v4.render --hold-changed song:... post:...
```

渲染速度：一首 4～5 分钟的歌，插帧 + 4K 编码约 25～30 分钟；成品约每秒 6MB。帧序列按剩余空间自动选 PNG / JPG，
画质高的源（Emptiness Machine）PNG 帧会占到 37GB。

## 进度

已出 4K 成品（21 首）：

| 场次 | 歌 |
|---|---|
| Shakira Live from Madrid 2026 | BZRP、Waka Waka、Dai Dai、GIRL LIKE ME、Antología、La fuerte、Te felicito、TQG、Can't Remember to Forget You、La bicicleta、Chantaje、Soltera、Te dejo Madrid、She Wolf |
| 单曲 | Lose Yourself、Emptiness Machine、Sarà perché（1983）、Sarà perché（2023）、Ricchi e Poveri Sanremo 2020 串烧、HKT48 そばにいるね、そばにいるね |

还没渲染、等人定（11 首，`concerts/render_v4_hold.json`；时间是审核页表格时间）：

| 类别 | 歌 | v4 和 v3 的区别 | 建议 |
|---|---|---|---|
| 几乎没差别 | La tortura | 两句差 0.01 s | v4 |
| | Acróstico | 一句早 0.9 s | v4 |
| | Copa vacía | 一句晚 1 s | v4 |
| | Don't Bother | 去掉半截的「Don't miss」，一句晚 1 s | v4 |
| v4 更好 | Ojos así | 0:10～0:32 乱识别 → 真歌词（不是合唱检测，是 v3 结果比代码旧） | v4 |
| | Pies descalzos | 合唱段 15 句碎片 → 8 句正确歌词（已重切，见下） | v4 |
| | Suerte | 2:20 碎片 → 「Le ro, lo le, lo le」 | v4 |
| 合唱判错 | Hips Don't Lie | 2:41 歌手喊「Yeah, oh, yeah, ladies」被判成合唱，晚出 4 s | v3 |
| | Empire | 3:32 一句顺序反了、只闪 0.3 s；4:25 一句提前 6 s | v3 |
| | Las de la intuición | 0:41～0:48 丢了真唱的「Despacio, despacio…」「Como si nos deseábamos」 | v3 |
| | Loca | 0:32～1:02 v4 更好；1:50～2:00 把上一句重复了 10 s | v4，1:50 那段换回 v3 |

## 改过起止点的歌

| 歌 | 改动 | 备注 |
|---|---|---|
| Dai Dai | 起点往后 30 s（歌曲内时间） | v4 是切完后重跑的；开头 0:00～0:08 的幻听「Ayo」换回 v3（两句国家名，v3 判为幻听不显示）；原结果在 `reports/v4_before_opening_fix/`。**切的时候没清旧的节拍缓存（reports/beats.npy），v4 用的切点错位 30 s**，可能是 v4 比 v3 差的原因之一；要不要清缓存重跑待定 |
| Pies descalzos | 起点往后 15 s（播放器 0:25） | 没重新对齐，字幕整体平移；预览从新起点开始；旧的节拍 / 音高 / 立体声缓存挪到 `reports/before_trim/` |

重切音频的规则：预览视频从新起点开始（不再多留 10 s）；原文件备份到 `reports/before_trim/`；按旧时间轴算的缓存
（`reports/beats.npy`、`pitch.npz`、`stereo.npz`）要一起挪走，不然重跑会错位。

## 待办

- 11 首等人定的（上表）。
- Pies descalzos 12 句「改词」是识别碎片：0:28「Porrista avanzan」→「Tú mordiste la manzana」，2:37「No tocar」→
  「Es mejor no olvidar」，另外 10 句（「Mă simt bine」「Nu starea」等）去掉。还没改。
- Dai Dai 是否清缓存重跑 v4。
- 千问识别（qwen-audio-3.1-asr-flash）的 API key 现在报无效（401），新跑识别前要换 key；今天的 v4 都是用缓存跑的。
- 封面、投稿标题 / 简介还没做。
