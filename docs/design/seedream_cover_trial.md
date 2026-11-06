# Seedream 封面试跑

后续选帧默认遵循 [AI 封面选帧策略 v1](ai_cover_frame_selection.md)：三个不同构图各一张。以下 Dark Horse 三配色为早期试验记录。计划现支持每个 candidate 独立指定 reference、source_time、selection_reason；缺省时兼容计划级 reference。抖音另外提供纯 AI 加字预览，与旧模板独立展示。

2026-11-06：仅 Dark Horse 已完成 3 张母图、12 张平台试排预览。

- 服务：火山方舟，`doubao-seedream-5-0-flash-260915`。
- 参考：从原 TS 视频 1778.992 秒重新提取，非用户截图。
- 母图：2560×1440，无文字，暖红 / 冷蓝 / 紫金三种油画方向。
- B站：1920×1080、1440×1080；抖音：1080×1440、1440×1080。
- 三次请求均成功，usage 各为 input_images=1、generated_images=1；按公开单价估算生图 ¥0.36，非账户账单。
- UI 的 AI 生成展示这三张母图及原片参考入口，两平台 Tab 按母图分组展示四版试排；当前仅预览，不自动替换既有采用记录。

## 运行

后端环境提供 `ARK_API_KEY`；不要写入前端、提交到仓库或写进作业记录。本次凭据从用户指定的 Takit 本地部署配置读取，仅传入进程环境。

```sh
.venv/bin/python -m workflow.seedream_cover grammys_2014 04_dark_horse posts/grammys_2014/04_dark_horse/covers/ai/seedream-plan.json
```

计划包含 reference、source_time，以及 1–3 个 label / prompt 候选。当前计划及完整提示词保存在上述 JSON。命令每次只接收一首歌，无批量入口；页面加载和切换 Tab 不产生付费请求。

计划、参考图内容、模型共同确定 run ID。已保存的母图重跑时直接复用，只重做本地排版。请求超时或失败后保留状态，禁止自动重试，避免不确定结果造成重复计费。三个候选全部就绪后才更新 masters.json；旧素材保留。四版清单按母图更新，新增母图不会覆盖其他母图的预览。

## 验证

已检查 3 张母图与 12 张成品的尺寸、HTTP 图片响应，以及浏览器三个相关 Tab 的母图分组。两项模拟测试验证重复运行不再请求付费 API，以及不确定失败不自动重试。

```sh
.venv/bin/python -m unittest discover -s tests -p test_seedream_cover.py
```

## 与双平台制作接入（2026-11-06）

`workflow.dual_platform` 已提供 `--ai-cover-plan`，以及不重做视频的 `--covers-only`。视频沿用既有苹果 HEVC 编码预设，共享一次插帧；AI 仍使用本模块的有界、缓存生成。

本次 Drunk in Love / Royals 各检查三个不同原片构图，生成成功各一张；另外四张因服务商输出内容审核拒绝，未重试。显式 `--skip-failed-covers` 只跳过已有失败并处理未尝试候选，不重复请求。Royals 另保留此前一张成功母图；更新清单保留不同母图的既有结果。

两曲的 `delivery_bundle.json` 集中记录成品、投稿文案、AI 封面与失败项；选择状态保持待用户采用，不自动替换封面或投稿。原片抽帧联系表、精细抽帧与比例检查图位于 `work/ai-two-songs/`。
