#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Qwen3-ASR 确定“这一版实际演唱的歌词顺序”（不管时间）：
  1. 人声在安静处切成 10~20s 的块（不重叠），逐块 qwen3-asr-flash 识别（不给上下文，给了会照抄）
  2. 每块识别文字按读音，从左到右贪心匹配参考歌词句（rapidfuzz 对齐，>= 门槛才认），得到块内的句子序列
  3. 拼成全曲演唱序列，写成新的参考歌词 txt（一行一句，按演唱顺序，文字仍来自参考歌词）
之后 decode_global --strict-order true 用这个序列做声学全局解码，MMS 负责精确时间。

python workflow/qwen_sequence.py --ref ori_lyrics/X.txt --vocals .../vocals.wav --lang ja -o work/X/sung_order.txt
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402
import llm  # noqa: E402
from textnorm import reading  # noqa: E402
from qwen_asr import ENDPOINT, SR, transcribe  # noqa: E402


def chunk_points(y, lo=10.0, hi=20.0):
    """在 [lo, hi] 秒范围内找人声能量最低处切块。"""
    hop = int(SR * 0.05)
    k = len(y) // hop
    e = np.sqrt((y[: k * hop].reshape(k, hop) ** 2).mean(1))
    e = np.convolve(e, np.ones(6) / 6, mode="same")
    cuts, t = [0.0], 0.0
    total = len(y) / SR
    while total - t > hi:
        a, b = int((t + lo) / 0.05), int((t + hi) / 0.05)
        t = (a + int(np.argmin(e[a:b]))) * 0.05
        cuts.append(t)
    cuts.append(total)
    return list(zip(cuts[:-1], cuts[1:]))


def greedy_lines(text, refs, min_score):
    """识别文字 -> 参考句序号序列（从左到右，每次取起点最靠左、同起点取最长的达标匹配）。"""
    from rapidfuzz import fuzz

    r = reading(text)
    seq, pos = [], 0
    while pos < len(r) - 3:
        best = None
        for i, rr in enumerate(refs):
            if len(rr) < 4:
                continue
            al = fuzz.partial_ratio_alignment(rr, r[pos:pos + len(rr) * 2 + 6])
            if not al or al.score < min_score:
                continue
            cover = (al.src_end - al.src_start) / len(rr)
            if cover < 0.6:
                continue
            key = (al.dest_start, -len(rr) * al.score)
            if best is None or key < best[0]:
                best = (key, i, pos + al.dest_end)
        if best is None:
            pos += 1
            continue
        seq.append(best[1])
        pos = best[2]
    return seq


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--min-score", type=float, default=75)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    a = p.parse_args()

    import librosa
    from openai import OpenAI

    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    chunks = chunk_points(y)
    lines = [t for t, _ in acoustic.section_lines(a.ref)]
    uniq = sorted(set(lines), key=lines.index)
    refs = [reading(t) for t in uniq]

    with ThreadPoolExecutor(6) as ex:
        texts = [t or "" for t in ex.map(lambda c: transcribe(client, y[int(c[0] * SR):int(c[1] * SR)], a.lang), chunks)]

    order, per_chunk = [], []
    for (t0, t1), text in zip(chunks, texts):
        seq = greedy_lines(text, refs, a.min_score)
        per_chunk.append({"start": round(t0, 1), "end": round(t1, 1), "lines": [uniq.index(uniq[i]) + 1 for i in seq],
                          "asr_chars": len(text)})
        order.extend(seq)
    Path(a.output).write_text("\n".join(uniq[i] for i in order) + "\n", encoding="utf-8")
    if a.report:
        Path(a.report).write_text(json.dumps({"chunks": per_chunk, "sung_lines": len(order)}, ensure_ascii=False, indent=1))
    print(f"{len(chunks)} 块，识别出演唱序列 {len(order)} 句（参考里不同的句子 {len(uniq)} 种）；写入 {a.output}")
    for c in per_chunk:
        print(f"  {c['start']:6.1f}-{c['end']:6.1f}s: {c['lines']}")


if __name__ == "__main__":
    main()
