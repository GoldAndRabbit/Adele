#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把过长的字幕行拆成两句（必要时递归继续拆），时间轴按人声对齐。

断点: 文本里的空格 / 全角空格 / 标点，选左右宽度最均衡的那个
切点: 先按字数比例估计时刻，再在附近找 demucs 人声能量最低处（换气/停顿）

python workflow/split_long.py posts/X/lyrics.srt --vocals posts/X/vocals.wav [--max-width 40]
"""

import argparse
import re
import unicodedata

import numpy as np
import pysubs2

BREAK_RE = re.compile(r"[\s　]+|(?<=[、。，,！？!?])")
HOP = 0.01  # 能量曲线 10ms 一点


def width(s):
    """显示宽度：中日韩全角字符算 2。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s.strip())


def load_energy(path):
    import librosa

    y, sr = librosa.load(path, sr=16000, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=640, hop_length=int(sr * HOP))[0]
    # 平滑 100ms，避免被单个辅音的空隙骗到
    return np.convolve(rms, np.ones(10) / 10, mode="same")


def best_break(text):
    """返回 (左, 右)；找不到断点返回 None。"""
    total = width(text)
    best = None
    for m in BREAK_RE.finditer(text):
        left, right = text[:m.start()].strip(), text[m.end():].strip()
        if not left or not right:
            continue
        score = abs(width(left) - width(right))
        if best is None or score < best[0]:
            best = (score, left, right)
    if best is None or min(width(best[1]), width(best[2])) < total * 0.2:
        return None
    return best[1], best[2]


def split_time(start, end, left, right, energy, min_part=600):
    """按宽度比例估计切点，再在 ±800ms（不超过时长 25%）内找人声能量最低点。"""
    dur = end - start
    est = start + dur * width(left) / (width(left) + width(right))
    win = min(800, dur * 0.25)
    lo = max(start + min_part, est - win)
    hi = min(end - min_part, est + win)
    if energy is None or hi <= lo:
        return int(est)
    a, b = int(lo / 1000 / HOP), int(hi / 1000 / HOP)
    seg = energy[a:b]
    if len(seg) == 0:
        return int(est)
    # 同样低的情况下偏向估计点附近
    dist = np.abs(np.arange(a, b) * HOP * 1000 - est) / max(win, 1)
    idx = int(np.argmin(seg / (seg.max() + 1e-9) + 0.15 * dist))
    return int((a + idx) * HOP * 1000)


def split_event(e, max_w, energy):
    text = e.plaintext.replace("\n", " ").strip()
    if width(text) <= max_w:
        return [e]
    parts = best_break(text)
    if not parts:
        return [e]
    left, right = parts
    t = split_time(e.start, e.end, left, right, energy)
    a = pysubs2.SSAEvent(start=e.start, end=t, text=left)
    b = pysubs2.SSAEvent(start=t, end=e.end, text=right)
    return split_event(a, max_w, energy) + split_event(b, max_w, energy)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("--vocals", help="demucs 分离出的人声 wav，没有则只按字数比例切")
    p.add_argument("--max-width", type=int, default=40)
    p.add_argument("-o", "--output", help="默认原地覆盖")
    a = p.parse_args()

    subs = pysubs2.load(a.srt)
    energy = load_energy(a.vocals) if a.vocals else None
    before = len(subs.events)
    subs.events = [x for e in subs.events for x in split_event(e, a.max_width, energy)]
    subs.save(a.output or a.srt)
    still = sum(width(e.plaintext) > a.max_width for e in subs.events)
    print(f"{before} 句 -> {len(subs.events)} 句；仍超过 {a.max_width} 宽（无合适断点）: {still}")


if __name__ == "__main__":
    main()
