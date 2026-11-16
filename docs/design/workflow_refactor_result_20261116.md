# 标准工作流重构结果

2026-11-16 · 本地实现与验证记录，尚未推送

唯一入口为 `workflow.live`，七个模块定义在 `live/stages.py`，唯一项目／批次编排在 `live/pipeline.py`。本地与双Mac共用 `runtime.HostPool`，单曲准备和交付由 `delivery` 执行，编码引擎复用苹果流式或多渠道共享策略。当前操作见 [标准工作流](/Users/gold/repos/adele/docs/workflow.md)。

## 已完成的收拢

| 原实现 | 现在的归属 |
| --- | --- |
| `make_mv.py` 下载及音轨检查 | `download.py`、`media.py`；旧RIFE帧序列链删除 |
| `song/render.py`、`live/hd.py` | `live.stages.delivery → delivery → dual_platform.encode_job`；预设独立在 `encoding.py` |
| `priority_delivery.py` | `live.pipeline` 与 `runtime.HostPool`；不再有两层机器分组策略 |
| `concert_delivery.py` | `delivery.py` 仅执行单首，本地与SSH使用相同worker |
| `delivery_queue.py` | 退出依赖封面整库完成的另一套成品队列 |
| `fibo_dual_queue.py`、`fibo_concert`与`fibo_library`旧批次循环 | 封面业务在 `covers`，复用相同HostPool；单曲生成与参考帧工具保留 |
| `preview_batch.py` | `preview.py` 浏览器预览服务，删除旧预览／AI组合批次 |
| `subtitle_metadata_batch.py` | `metadata.py` 显式诊断函数，不再隐式编排全库 |
| `vertical_workflow`原准备／封面／发布组合入口 | 删除其总流程CLI，保留现有资料需要的字幕和版本读取等工具 |
| 整场先分离人声 | 拆分使用字幕轨／按窗口识别原音频，分离与精校在逐曲阶段执行，减少整场模型内存占用 |

共删除272个已备份、未改动且没有活动进程的旧批次Python脚本。原路径与SHA-256见 `removed_legacy_scripts.json`。重构前源码在 `main` 提交 `5c380b3`，历史查询不依赖当前工作树保留另一套归档脚本。

原片、字幕人工定稿、封面版本、既有成品、日志、修改前备份和真实投稿回执均保留。现有数据仍可读取，不以重构为由重新识别、出图或编码。

## 投稿资料与封面

字段顺序、字数限制、正文三部分、标签与封面命名共享 `templates.py`。B站自动标题由 `bili_title` 按完整字段预算；简介由 `make_meta.generate_intro` 先生成完整初稿、再按句删减；完整简介缺标签时只补12个有效标签，不重写正文。人工覆盖通过 `submission_records` 保留。

当前正式FIBO四比例封面共用 `compact_cover_text`，由 `ai_cover.branded_cover` 填入原文歌名、正式署名与演出信息。预览片头与保留旧版布局另行说明，避免将五行旧布局误认成当前AI封面。新封面发布与成品交付均调用 `write_bundle` 同步路径、机器、用时和两平台完整资料。

详细模板、例子和代码位置见 [投稿文案与封面文字模板](/Users/gold/repos/adele/docs/design/publication_templates.md)。

## 验证

- 常规测试发现274项，272项执行通过，2项实机测试按设计跳过；同两项实机测试另行开启并通过。
- 实机测试使用合成两秒素材，覆盖本机原生60fps、本机30→60和副机30→60，检查4K HEVC、FLAC音轨、流式策略及SSH回传摘要。
- 已确认队列的任务预演只选择 `delivery`，实际剩余10首；不调ASR、封面或投稿生成，不包含已交付的19首。
- 静态语法、文档目标链接和Git差异检查通过。新增架构回归禁止正式业务模块从 `work / posts / concerts` 导入批次代码。
- 原有两项基线失败已修正：失效合集底图选择回退到现有候选；未启用抖音合集时不默认入队。

此次没有重做字幕或封面的真实模型推理；相关算法沿用原模块与回归测试。当前恢复范围仅为已经确认预览的B站4K成品。

## 后续运行与Git状态

按用户指令，重构保持本地，不推送。远端 `main` 的重构前备份为 `5c380b3`。恢复命令为：

```bash
.venv/bin/python -u -m workflow.live run --batch posts/concert_delivery_20261116 --from delivery --to delivery --confirmed --resume
```

仍然只制作、不投稿；两台Mac每台一首，完成后持续接续剩余曲目。项目约定已写入根目录 `AGENTS.md`，后续改进进入正式代码，批次目录只保存数据。
