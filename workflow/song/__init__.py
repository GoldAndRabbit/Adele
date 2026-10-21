# -*- coding: utf-8 -*-
"""每首歌的字幕和成品：多锚点互相校准的对齐（方案见 docs/design/unified_alignment.md）+ 观众合唱检测
（docs/design/crowd_detection.md）+ 翻译 / 注释 + 4K 渲染。

    listen.py                       第 0 步：按自然停顿切块、多遍识别
    align.py                        第 1~3 步：整首顺序对齐（词级动态规划）、锚点、锚点之间逐段校准
    run.py                          第 4~5 步：歌词外段落、时间、显示、翻译；入口
    song_crowd_workflow.py          观众合唱检测
    song_translation_workflow.py    翻译：初译 → 润色（直译版）→ 审校 → 诗意版 → 歌名
    song_note_workflow.py           顶部注释
    watermark.py                    歌曲中间的水印计划
    render.py                       4K60 成品
    reslice.py                      整场改边界后，字幕按整场时间重新分到各首

结果写到每首歌的 subs/。
"""
