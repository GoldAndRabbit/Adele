#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
歌词之外的说话（开场白、谢幕、互动）：找出没有歌词字幕、但有人声的段落，按停顿切句，逐句 Qwen 识别。
产物是单独的 speech.srt，translate 阶段会和歌词一起翻译，中文不加 ♪（和歌词区分）。

默认只处理第一句歌词之前和最后一句之后；--gaps 时也处理歌曲中间 >= --min-gap 秒的无字幕人声段。

python workflow/speech_asr.py posts/X/lyrics.srt --vocals posts/X/vocals.wav --lang en -o posts/X/speech.srt
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pysubs2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
from qwen_asr import ENDPOINT, SR, transcribe  # noqa: E402

HOP = 0.02


def voiced_mask(y):
    k = len(y) // int(SR * HOP)
    fr = y[: k * int(SR * HOP)].reshape(k, -1)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(10) / 10, mode="same")
    return db > np.percentile(db, 95) - 25


def segments(voiced, t0, t1, min_pause=0.45, max_len=6.0, min_len=0.6):
    """[t0, t1] 里的有声段，按 >= min_pause 的停顿切开，太长的再按最安静处切，太短的丢掉。"""
    a, b = int(t0 / HOP), int(t1 / HOP)
    v = voiced[a:b]
    segs, i = [], 0
    while i < len(v):
        if not v[i]:
            i += 1
            continue
        j, quiet = i, 0
        while j < len(v):
            quiet = quiet + 1 if not v[j] else 0
            if quiet * HOP >= min_pause:
                break
            j += 1
        s, e = t0 + i * HOP, t0 + (j - quiet) * HOP
        while e - s > max_len:  # 太长就在 max_len 处切
            segs.append((s, s + max_len))
            s += max_len
        if e - s >= min_len:
            segs.append((s, e))
        i = j + 1
    return segs


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt", help="歌词字幕（用来确定哪些地方已经有字幕）")
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--gaps", action="store_true", help="也处理歌曲中间较长的无字幕人声段")
    p.add_argument("--min-gap", type=float, default=5.0)
    p.add_argument("-o", "--output", required=True)
    a = p.parse_args()

    import librosa
    from openai import OpenAI

    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    dur = len(y) / SR
    voiced = voiced_mask(y)
    ev = pysubs2.load(a.srt).events
    first, last = (ev[0].start / 1000, ev[-1].end / 1000) if ev else (dur, 0.0)

    spans = [(0.0, max(0.0, first - 0.3)), (last + 0.3, dur)]
    if a.gaps:
        for x, z in zip(ev, ev[1:]):
            if z.start - x.end >= a.min_gap * 1000:
                spans.append((x.end / 1000 + 0.3, z.start / 1000 - 0.3))
    out = []
    for t0, t1 in spans:
        if t1 - t0 < 0.6:
            continue
        for s, e in segments(voiced, t0, t1):
            text = (transcribe(client, y[int(max(0, s - 0.15) * SR):int(min(dur, e + 0.15) * SR)], a.lang) or "").strip()
            if len(text) >= 2:
                out.append((s, e, text))
    subs = pysubs2.SSAFile()
    for s, e, t in out:
        subs.events.append(pysubs2.SSAEvent(start=int(s * 1000), end=int(e * 1000), text=t))
    subs.save(a.output)
    print(f"说话识别：{len(out)} 句（" + ", ".join(f"{int(s // 60)}:{s % 60:04.1f}" for s, _, _ in out[:12])
          + ("…" if len(out) > 12 else "") + f"）-> {a.output}")


if __name__ == "__main__":
    main()
