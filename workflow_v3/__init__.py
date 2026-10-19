# -*- coding: utf-8 -*-
"""v3 字幕精校：多锚点互相校准（一套方案，所有歌共用）。方案见 docs/design/v3_unified_alignment.md。

    listen.py  第 0 步：按自然停顿切块、多遍识别
    align.py   第 1~3 步：整首顺序对齐（词级动态规划）、锚点、锚点之间逐段校准
    run.py     第 4~5 步：歌词外段落、时间、显示、翻译；入口

结果写到每首歌的 exp_v3/，不动 v2（exp_v2/）。
"""
