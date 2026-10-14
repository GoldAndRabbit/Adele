#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕时间轴客观评测（多个版本对比）：
  on_cue     字幕出现时（含 0.12s 提前量）人声能量增益 > 3dB 的比例 —— 踩点
  gain_med   上述增益中位数（dB）
  ev_med     声学证据中位数（这句的声音像不像在唱这句，越大越好）
  low        声学证据低于门槛（错句/错位嫌疑）的句数
  coverage   有人声的时间里有字幕的比例 —— 漏字幕
  overshow   没人声的时间里还挂着字幕的比例 —— 字幕拖太久/提前

python pipeline/eval_subs.py --vocals .../vocals.wav --lang ja v1.srt v2.srt ...
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pysubs2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srts", nargs="+")
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--lead", type=float, default=0.12)
    p.add_argument("--min-ev", type=float, default=None, help="错句门槛，默认按第一个版本的分布")
    a = p.parse_args()

    sc = acoustic.Scorer(a.vocals, a.lang)
    y = sc.y
    hop = 160
    k = len(y) // hop
    db = 20 * np.log10(np.sqrt((y[: k * hop].reshape(k, hop) ** 2).mean(1)) + 1e-9)
    db_s = np.convolve(db, np.ones(25) / 25, mode="same")
    voiced = db_s > np.percentile(db_s, 95) - 18

    def gain(t):
        i = int(t * 100)
        return db[i:i + 30].mean() - db[max(0, i - 30):i].mean() if i > 0 else 0.0

    min_ev = a.min_ev
    print(f"{'version':28} {'lines':>5} {'on_cue':>7} {'gain_med':>8} {'ev_med':>7} {'low':>4} {'coverage':>8} {'overshow':>8}")
    for path in a.srts:
        ev = pysubs2.load(path).events
        g = np.array([gain(e.start / 1000 + a.lead) for e in ev])
        v = np.array([sc.evidence(e.plaintext, e.start / 1000, e.end / 1000) for e in ev])
        if min_ev is None:
            min_ev = float(np.percentile(v, 25) - 0.5 * v.std())
        shown = np.zeros(k, bool)
        for e in ev:
            shown[int(e.start / 10):int(e.end / 10)] = True
        cov = (shown & voiced).sum() / max(1, voiced.sum())
        over = (shown & ~voiced).sum() / max(1, shown.sum())
        print(f"{Path(path).name:28} {len(ev):5} {np.mean(g > 3) * 100:6.0f}% {np.median(g):8.1f} "
              f"{np.median(v):7.2f} {int((v < min_ev).sum()):4} {cov * 100:7.0f}% {over * 100:7.0f}%")
    print(f"(low 门槛 {min_ev:.2f})")


if __name__ == "__main__":
    main()
