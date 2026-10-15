#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
歌词主导对齐：认定参考歌词就是演唱顺序，整首歌词一次性用 MMS 强制对齐到人声上，只定时间。
适合说唱等 ASR 很难识别、但基本按原词演唱的歌（Qwen 单句识别不稳，不该由它决定结构）。
句与句之间放 * 吸收间奏、喊话、和声；对不上的句子（分数过低或时长离谱）丢掉不显示。

python workflow/lyrics_align.py --ref posts/X/lyrics.txt --vocals posts/X/vocals.wav --lang en -o posts/X/lyrics.srt
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pysubs2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402
from refine_timing import SR, align_global, load_model, romanize  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--min-score", type=float, default=0.0, help="对齐平均 token 概率（log）低于这个的句子丢掉，0 表示不过滤")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    a = p.parse_args()

    import librosa
    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    model, tokenizer, aligner = load_model()
    lines = [t for t, _ in acoustic.section_lines(a.ref)]
    words = [romanize(t, a.lang) for t in lines]
    res = align_global(model, tokenizer, aligner, y, words)

    out, dropped = [], []
    for i, (t, r) in enumerate(zip(lines, res)):
        if r is None:
            dropped.append(i + 1)
            continue
        t0, t1, sc = r
        n = max(1, sum(len(w) for w in words[i]))
        dur = t1 - t0
        # 时长离谱（被压成一瞬或拉得极长）说明这句没在这里唱，丢掉
        if dur < 0.15 or dur > max(10.0, n * 0.5) or (a.min_score and sc < a.min_score):
            dropped.append(i + 1)
            continue
        out.append((t0, t1, t))
    out.sort()
    subs = pysubs2.SSAFile()
    for k, (t0, t1, t) in enumerate(out):
        if k + 1 < len(out):
            t1 = min(t1, out[k + 1][0] - 0.03)
        subs.events.append(pysubs2.SSAEvent(start=int(t0 * 1000), end=int(max(t1, t0 + 0.5) * 1000), text=t))
    subs.save(a.output)
    if a.report:
        Path(a.report).write_text(json.dumps({"lines": len(lines), "kept": len(out), "dropped": dropped}, indent=1))
    print(f"歌词主导对齐：参考 {len(lines)} 句，定位 {len(out)} 句，丢弃 {len(dropped)} 句")


if __name__ == "__main__":
    main()
