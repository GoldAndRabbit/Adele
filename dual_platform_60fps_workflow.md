# 成品编码与双平台设计

唯一操作入口见 [标准工作流](docs/workflow.md)，文案与封面填字见 [模板规范](docs/design/publication_templates.md)。本文件只说明编码约束，不另定义批次流程。

## 输入与渠道

输入读取正式原片选择和逐曲切片，支持普通MP4、MKV、MOV及TS，不限定TS。默认B站单渠道；`delivery_defaults.json` 的 render_platforms、collection_platforms 和 single_channel_pipeline 是共用默认，单首 policy.json 固化实际选择，制作期间不受后来配置变化影响。

| 渠道 | 输出 |
| --- | --- |
| B站 | 3840×2160、60fps、HEVC、FLAC 48kHz/24bit、MP4 |
| 抖音（显式选择） | 1080×1920、60fps、HEVC、AAC 48kHz/320kbps、MP4 |

编码预设唯一位于 `workflow/encoding.py`，默认 hevc_hw：苹果 VideoToolbox HEVC，35Mbps、峰值50Mbps、缓冲70Mbps、Main、hvc1。合成器、字幕、水印和颜色策略由 `dual_render` 与 `original_master.video_recipe` 共用，不另写第二份编码参数。

## 单渠道：直接流式制作

```text
确认原片与切片
  → 解码、按源类型去隔行／颜色归一化
  → 苹果插帧到60fps（原生60fps跳过）
  → 字幕、水印与画面合成
  → 苹果HEVC最终编码
  → 基本规格检查、返回摘要与安装成品
```

`stream_delivery.encode` 使用有界管道和背压。只有音频与切镜索引暂存在执行Mac的内置盘，不写原帧图片、60fps帧图片或中间视频。插帧和编码重叠执行，timings中的融合阶段耗时不能再加一遍虚构的独立插帧耗时。任一子进程失败，会回收解码、插帧、编码整组进程，半成品不发布。

MPEG-TS与特殊音频解码发生快速seek空音轨或时钟间隔丢失时，先用同一解码器从头重建音频时钟，使用 aresample=async=1:first_pts=0，再按实际输出时钟切片。恢复失败就记录本首错误，不把零音轨当成功，不对整批重新做听审。

## 双渠道：共享处理

明确选择两渠道时，`dual_platform.encode_job` 使用 `original_master` 或对应去隔行分支准备共享60fps母版，再由 `dual_render` 编码两版。共享母版仅是双渠道策略，不是B站单渠道的必经步骤。TS隔行按既有bwdif策略处理，普通源保留原始帧率直到插帧阶段；切镜、闪光与重复帧规则沿用已验证引擎。

## 双Mac与存储

`live.pipeline → runtime.HostPool` 是唯一任务调度。每台一首、完成后领取下一首，可跨演出；`delivery.run` 只负责一个任务。主机与副机执行同一 `delivery.worker → encode_job`，副机原片按摘要缓存复用，只有压力下才清理可重建副本。

原片和最终成品在 harddisk_5T，插帧与临时处理在执行Mac的内置盘。副机先在本机完成编码，再回传主机外盘。作业锁、用户暂停和制作期间输入版本变化均受保护；仅在成品实际就绪、回传完整后切换 products 链接。既有成品与人工定稿不随失败清理删除。

## 交付与资料同步

每首保留 render_status.json、products.json、timings.json 和完整日志，记录实际执行机器、起止时间、准备与编码用时、回传用时及文件摘要。通过 `delivery_bundle.write_bundle` 更新投稿页的输入成品路径、制作机器、用时和封面路径，页面与导出共用资料。

成品仅检查所选渠道的轨道、规格、时长、输入版本和传输完整性；已确认预览不重复跑ASR、歌词修复或音频波形听审。制作不会自动发布。

## 验证

`.venv/bin/python -m unittest discover -s tests` 覆盖渠道选择、输入冻结、解码恢复、进程回收、暂停和双机派工。`tests/test_media_smoke.py` 使用两秒合成素材实测原生60fps、30→60和SSH回传，详见标准工作流。
