# -*- coding: utf-8 -*-
"""separate：整场人声分离只跑一次（v1 的 Mel-Band RoFormer），每首歌的人声从这里切片。"""

import sys

from .paths import ROOT, SEP_PY
from .util import run


def stage_separate(c, a):
    if c.vocals.exists() and not a.force:
        print(f"已存在 {c.vocals}")
        return
    if not SEP_PY.exists():
        sys.exit("缺少人声分离环境 .venv-sep（见 README 安装说明）")
    tmp = c.vocals.with_suffix(".partial.wav")
    run([SEP_PY, ROOT / "workflow" / "separate_roformer.py", c.audio, "-o", tmp])
    tmp.replace(c.vocals)
