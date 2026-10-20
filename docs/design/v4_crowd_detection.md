# v4：v3 + 观众合唱检测

v4 单独一个目录 `workflow_v4/`，从 `workflow_v3/` 复制出来后单独维护，两边不共用代码：改 v4 不影响 v3，v3 也不再有观众合唱检测。

| | v3 | v4 |
|---|---|---|
| 代码 | `workflow_v3/` | `workflow_v4/` |
| 结果 | 每首歌的 `exp_v3/` | 每首歌的 `exp_v4/` |
| 观众合唱检测 | 没有 | 有（`song_crowd_workflow.py`） |
| 其余步骤（识别、对齐、翻译、注释、水印） | 原样 | 复制时和 v3 一样，之后各改各的 |

## 流程

```
听（多遍识别）→ 整首顺序对齐 → 锚点 → 锚点之间重新识别、再对齐
  → 观众合唱检测（v4 才有）
  → 歌词外段落 → 时间 → 显示 → 翻译（song_translation_workflow）→ 注释（song_note_workflow）
```

观众合唱检测在两个可靠锚点之间找「有人声、识别很碎、按歌词顺序该唱 ≥ 1 句」的区间，各项证据独立打分：
识别碎片、立体声、主唱音高稳定度、画面（Qwen-VL 看 3 帧）、提示语（canten / sing / everybody …）、歌词顺序。
判成观众合唱的段，该唱的句子按 Genius 顺序排进去，时间按录音室版 LRC（lrclib.net）的时长比例分。
检测结果写到 `exp_v4/crowd.json`，审核页表格里「唱法」列标出来。

## 运行

```
.venv/bin/python -m workflow_v4.run song shakira_madrid_2026 28_antologia
.venv/bin/python -m workflow_v4.run post emptiness_machine
.venv/bin/python -m workflow_v4.watermark post emptiness_machine
```

只跑点名的那首；多首一起跑要先确认。
