#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分块对齐：Qwen3-ASR 已经给出每个时间块唱了哪几句、什么顺序（qwen_sequence.py 的 sung_order.txt/json），
直接在每块的时间范围里用 MMS 把这几句按顺序强制对齐，得到每句起止。不做全局解码、不做换句推断。

python pipeline/chunk_align.py --order work/X/sung_order.txt --chunks work/X/sung_order.json \
    --vocals separated/roformer/X/vocals.wav --lang ja -o out.srt
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pysubs2
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refine_timing import SR, load_model, romanize  # noqa: E402

PAD = 0.8  # 块边界前后各放宽多少秒（句子可能跨块边界）


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--order", required=True)
    p.add_argument("--chunks", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("-o", "--output", required=True)
    a = p.parse_args()

    import librosa
    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    model, tokenizer, aligner = load_model()
    lines = [l for l in Path(a.order).read_text(encoding="utf-8").splitlines() if l.strip()]
    chunks = json.loads(Path(a.chunks).read_text())["chunks"]

    out, pos, failed = [], 0, []
    for c in chunks:
        n = len(c["lines"])
        texts = lines[pos:pos + n]
        pos += n
        if not texts:
            continue
        t0, t1 = max(0.0, c["start"] - PAD), min(len(y) / SR, c["end"] + PAD)
        seg = torch.from_numpy(y[int(t0 * SR):int(t1 * SR)]).float().unsqueeze(0)
        with torch.inference_mode():
            em, _ = model(seg)
        fr = em.shape[1] / (t1 - t0)
        words, owner = ["*"], [None]
        for k, t in enumerate(texts):
            for w in romanize(t, a.lang):
                words.append(w)
                owner.append(k)
            words.append("*")
            owner.append(None)
        try:
            spans = aligner(em[0], tokenizer(words))
        except Exception:
            failed.append(c["start"])
            continue
        res = {}
        for sp, k in zip(spans, owner):
            if k is None or not sp:
                continue
            s_, e_ = t0 + sp[0].start / fr, t0 + sp[-1].end / fr
            res[k] = (min(res[k][0], s_), max(res[k][1], e_)) if k in res else (s_, e_)
        for k, t in enumerate(texts):
            if k in res:
                out.append((res[k][0], res[k][1], t))

    out.sort()
    subs = pysubs2.SSAFile()
    for k, (s_, e_, t) in enumerate(out):
        if k + 1 < len(out):
            e_ = min(e_, out[k + 1][0] - 0.03)
        subs.events.append(pysubs2.SSAEvent(start=int(s_ * 1000), end=int(max(e_, s_ + 0.5) * 1000), text=t))
    subs.save(a.output)
    print(f"分块对齐: {len(chunks)} 块，{len(out)} 句" + (f"；对齐失败的块 {failed}" if failed else ""))


if __name__ == "__main__":
    main()
