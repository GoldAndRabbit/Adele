#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
密集窗口结构识别：人声按 2.5s 窗口、0.5s 步长逐窗 Qwen 识别，每窗匹配参考歌词里最像的一句（读音模糊匹配），
连续窗口同一句合并成一段 -> 这一句大致在这里唱。比 10~20s 的大块细得多，能分清副歌和长得像的尾段/改编段。
输出粗时间轴 srt（文字只来自参考歌词），之后交给 refine_timing 强制对齐精修。

python workflow/qwen_dense.py --ref posts/X/lyrics.txt --vocals posts/X/vocals.wav --lang en -o out.srt --report r.json
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pysubs2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402
import llm  # noqa: E402
from qwen_asr import ENDPOINT, SR, transcribe  # noqa: E402
from textnorm import reading  # noqa: E402

WIN, HOP, MIN_SCORE = 2.5, 0.5, 75


def tighten(runs, y, lang, pad=0.6):
    """逐句局部强制对齐：每句只在密集窗口给的位置 ±pad 秒内用 MMS 找精确起止，不会漂到别的句子上。"""
    import torch
    from refine_timing import emission_full, load_model, romanize, snap_onset, onset_curve

    model, tokenizer, aligner = load_model()
    em, fr = emission_full(model, y)
    _, rise = onset_curve(y)
    out = []
    for k, (s, e, t) in enumerate(runs):
        lo = max(0.0, s - pad, runs[k - 1][1] - 0.2 if k else 0.0)
        hi = min(len(y) / SR, e + pad, runs[k + 1][0] + 0.2 if k + 1 < len(runs) else 1e9)
        words = romanize(t, lang)
        a0, a1 = int(lo * fr), int(hi * fr)
        if not words or a1 - a0 < 10:
            out.append([s, e, t])
            continue
        try:
            spans = aligner(em[a0:a1], tokenizer(["*"] + words + ["*"]))[1:-1]
            ns, ne = lo + spans[0][0].start / fr, lo + spans[-1][-1].end / fr
            if ne - ns > 0.3 and abs(ns - s) < pad + 0.3:
                s, e = snap_onset(ns, rise), ne
        except Exception:  # noqa: BLE001
            pass
        out.append([s, e, t])
    for x, z in zip(out, out[1:]):
        if z[0] < x[1]:
            x[1] = max(x[0] + 0.3, z[0] - 0.03)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--no-tighten", dest="tighten", action="store_false", help="不做逐句局部强制对齐")
    p.add_argument("--cache", help="窗口识别缓存 json（重跑不再调 API）")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    a = p.parse_args()

    import librosa
    from openai import OpenAI
    from rapidfuzz import fuzz

    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    dur = len(y) / SR
    hop = int(HOP * SR)
    k = len(y) // hop
    db = 20 * np.log10(np.sqrt((y[: k * hop].reshape(k, hop) ** 2).mean(1)) + 1e-9)
    loud = np.percentile(db, 95)
    starts = [round(t, 2) for t in np.arange(0, max(0.0, dur - 1.0), HOP)]

    cache = {}
    if a.cache and os.path.exists(a.cache):
        cache = json.load(open(a.cache))
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])

    def job(t):
        key = f"{t:.2f}"
        if key in cache:
            return cache[key]
        i0, i1 = int(t / HOP), int((t + WIN) / HOP)
        if db[i0:i1].size == 0 or db[i0:i1].max() < loud - 25:  # 基本没人声
            return ""
        return transcribe(client, y[int(t * SR):int(min(dur, t + WIN) * SR)], a.lang) or ""

    with ThreadPoolExecutor(3) as ex:
        texts = list(ex.map(job, starts))
    if a.cache:
        cache.update({f"{t:.2f}": x for t, x in zip(starts, texts)})
        json.dump(cache, open(a.cache, "w"), ensure_ascii=False)

    lines = [t for t, _ in acoustic.section_lines(a.ref)]
    uniq = sorted(set(lines), key=lines.index)
    ur = {t: reading(t) for t in uniq}
    best = []
    for t, x in zip(starts, texts):
        r = reading(x)
        if len(r) < 6:
            best.append(None)
            continue
        sc, txt = max((fuzz.partial_ratio(ur[u], r), u) for u in uniq if len(ur[u]) >= 6)
        best.append(txt if sc >= MIN_SCORE else None)

    # 连续窗口同一句合并（允许中间断 1 窗）；一句唱的时间 ≈ 第一个命中窗口的开头 ~ 最后一个命中窗口的结尾
    runs, i = [], 0
    while i < len(best):
        if best[i] is None:
            i += 1
            continue
        txt, j, last = best[i], i, i
        while j + 1 < len(best) and (best[j + 1] == txt or (best[j + 1] is None and j + 2 < len(best) and best[j + 2] == txt)):
            j += 1
            if best[j] == txt:
                last = j
        runs.append([starts[i], starts[last] + WIN, txt])
        i = last + 1
    # 窗口有 2.5s 宽，相邻句的命中范围会重叠：取重叠中点为分界
    for x, z in zip(runs, runs[1:]):
        if z[0] < x[1]:
            mid = (z[0] + x[1]) / 2
            x[1], z[0] = mid, mid
    runs = [r for r in runs if r[1] - r[0] >= 0.6]

    if a.tighten:
        runs = tighten(runs, y, a.lang)

    subs = pysubs2.SSAFile()
    for s, e, t in runs:
        subs.events.append(pysubs2.SSAEvent(start=int(s * 1000), end=int(e * 1000), text=t))
    subs.save(a.output)
    if a.report:
        Path(a.report).write_text(json.dumps({"windows": len(starts), "matched": sum(1 for b in best if b),
                                              "lines": len(runs)}, indent=1))
    print(f"密集窗口：{len(starts)} 窗，命中 {sum(1 for b in best if b)} 窗 -> {len(runs)} 句")


if __name__ == "__main__":
    main()
