# -*- coding: utf-8 -*-
"""整场演唱会流程：整场演唱会 -> 单曲拆分 -> 逐首精校字幕 / 封面 / 介绍 -> 人工审核 -> 只对通过的歌做高清。见 docs/design/concert_pipeline.md。"""

import sys
from pathlib import Path

# 复用 workflow/ 下的模块（那里的脚本都是平铺 import 的）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # workflow/
