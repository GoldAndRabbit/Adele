#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕时间轴精校：已知歌词文本 → 强制对齐到人声波形，再吸附到起音点，加显示提前量。

  1. 强制对齐：torchaudio MMS_FA（多语种 CTC 对齐模型）。英文直接用字母，日文先用 pykakasi 转罗马音。
     整首歌所有句子按顺序一次性对齐（句间放 * 吸收间奏/和声/喊话），句与句互相约束，不会抢到前后句；
     取每句首字起点/末字终点
  2. 起音吸附：在新起点 ±0.15s 内找人声能量上升最快处
  3. 提前量：字幕比开口早 --lead 秒出现（默认 0.12s）；不与下一句重叠，最短显示 0.8s
  和原时间差太远（> 2.5s，多半是对齐跑偏）的句子保持原时间，在报告里列出

python workflow/refine_timing.py songs/X/lyrics.srt --vocals songs/X/vocals.wav --lang en -o songs/X/lyrics.srt
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pysubs2
import torch

SR = 16000
PAD = 1.2          # 对齐窗口前后各扩多少秒
MIN_SCORE = 0.25   # 对齐平均分低于这个视为不可信
SNAP = 0.15        # 起音吸附范围（秒）
MIN_DUR = 0.8
MAX_SHIFT = 2.5          # 新起点和原起点差在这个范围内直接采信
MAX_SHIFT_ORDERED = 6.0  # 差得更多时，和前后句顺序一致才采信


def romanize(text, lang):
    if lang == "ja":
        import pykakasi
        text = " ".join(item["hepburn"] for item in pykakasi.kakasi().convert(text))
    text = text.lower().replace("’", "'")
    words = [re.sub(r"[^a-z']", "", w) for w in re.split(r"[\s\-]+", text)]
    return [w for w in words if w.strip("'")]


def load_model():
    from torchaudio.pipelines import MMS_FA as bundle
    model = bundle.get_model(with_star=True).eval()
    return model, bundle.get_tokenizer(), bundle.get_aligner()


def onset_curve(y):
    hop = int(SR * 0.01)
    frames = len(y) // hop
    rms = np.sqrt(np.add.reduceat(y[: frames * hop] ** 2, np.arange(0, frames * hop, hop)) / hop + 1e-12)
    db = 20 * np.log10(rms)
    db = np.convolve(db, np.ones(5) / 5, mode="same")
    return db, np.diff(db, prepend=db[0])


def snap_onset(t, rise):
    i0, i1 = max(0, int((t - SNAP) * 100)), min(len(rise), int((t + SNAP) * 100) + 1)
    if i1 <= i0:
        return t
    i = i0 + int(np.argmax(rise[i0:i1]))
    return i / 100 if rise[i] > 1.0 else t  # 没有明显起音就不动


def emission_full(model, y, chunk_s=30):
    """整首歌分块算 CTC 发射概率再拼接（块间留 1s 重叠，取中间部分，避免边界失真）。"""
    hop = chunk_s * SR
    ctx = SR
    parts, frame_rate = [], None
    with torch.inference_mode():
        for s in range(0, len(y), hop):
            a0, a1 = max(0, s - ctx), min(len(y), s + hop + ctx)
            x = torch.from_numpy(y[a0:a1]).float().unsqueeze(0)
            if x.shape[1] < 400:
                continue
            em, _ = model(x)
            em = em[0]
            fr = em.shape[0] / ((a1 - a0) / SR)
            frame_rate = frame_rate or fr
            lo = int(round((s - a0) / SR * fr))
            hi = lo + int(round(min(hop, len(y) - s) / SR * fr))
            parts.append(em[lo:hi])
    return torch.cat(parts), frame_rate


def align_global(model, tokenizer, aligner, y, lines):
    """所有歌词按顺序一次性对齐整首歌；句与句之间放 * 吸收间奏、和声、喊话等不在歌词里的声音。
    返回每句 (起, 止, 分数)，romanize 后为空的句子返回 None。"""
    em, fr = emission_full(model, y)
    words, owner = ["*"], [None]
    for li, w in enumerate(lines):
        for x in w:
            words.append(x)
            owner.append(li)
        words.append("*")
        owner.append(None)
    spans = aligner(em, tokenizer(words))
    res = [None] * len(lines)
    for sp, li in zip(spans, owner):
        if li is None or not sp:
            continue
        t0, t1 = sp[0].start / fr, sp[-1].end / fr
        sc = [t.score for t in sp]
        if res[li] is None:
            res[li] = [t0, t1, sc]
        else:
            res[li][1] = t1
            res[li][2] = res[li][2] + sc
    return [None if r is None else (r[0], r[1], float(np.mean(r[2]))) for r in res]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default="en", help="en / ja（日文先转罗马音）")
    p.add_argument("--lead", type=float, default=0.12, help="字幕比开口提前出现的秒数")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    a = p.parse_args()

    import librosa
    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    _, rise = onset_curve(y)
    model, tokenizer, aligner = load_model()

    subs = pysubs2.load(a.srt)
    rows, kept = [], []
    lines = [romanize(ev.plaintext, a.lang) for ev in subs.events]
    aligned = align_global(model, tokenizer, aligner, y, lines)
    for i, (ev, res) in enumerate(zip(subs.events, aligned)):
        old_s, old_e = ev.start / 1000, ev.end / 1000
        # 全局对齐有前后句约束，主要防的是整段跑偏：和原时间差太远（> MAX_SHIFT）就不信
        # 位移小直接信；位移大（原时间本身可能是错的，比如开头把观众声当成了演唱）时，
        # 只要和前后句的新时间顺序一致、且不超过 MAX_SHIFT_ORDERED，也信
        prev_end = next((aligned[k][1] for k in range(i - 1, -1, -1) if aligned[k]), 0.0)
        next_start = next((aligned[k][0] for k in range(i + 1, len(aligned)) if aligned[k]), 1e9)
        ordered = res is not None and prev_end - 0.3 <= res[0] and res[1] <= next_start + 0.3
        shift = abs(res[0] - old_s) if res else 1e9
        ok = (res is not None and 0.2 < res[1] - res[0] < 12
              and (shift < MAX_SHIFT or (ordered and shift < MAX_SHIFT_ORDERED)))
        if ok:
            rows.append((i, snap_onset(res[0], rise), res[1], res[2]))
        else:
            rows.append((i, old_s, old_e, res[2] if res else 0.0))
            kept.append(i + 1)

    # 时长体检：按字数估算每句该唱多久，太短（<0.45 倍）或太长（>2.2 倍且 >3s）的视为对齐被挤压/拉伸；
    # 连续的异常句在前后两句可信句之间按字数重新分配，再吸附起音
    nchar = [max(1, sum(len(w) for w in lines[i])) for i in range(len(rows))]
    rate = sorted((r[2] - r[1]) / c for r, c in zip(rows, nchar) if r[2] > r[1])
    rate = rate[len(rate) // 2] if rate else 0.12
    def bad(k):
        d, exp = rows[k][2] - rows[k][1], nchar[k] * rate
        return d < exp * 0.45 or (d > exp * 2.2 and d > 3.0)
    redistributed = []
    k = 0
    while k < len(rows):
        if not bad(k):
            k += 1
            continue
        j = k
        while j < len(rows) and bad(j):
            j += 1
        # 拉长的句子旁边往往是被挤短的句子（它们的时间被抢走了），一起重新分配
        squeezed = lambda m: rows[m][2] - rows[m][1] < nchar[m] * rate * 0.75
        while k > 0 and squeezed(k - 1) and (k - 1) + 1 not in redistributed:
            k -= 1
        while j < len(rows) and squeezed(j):
            j += 1
        lo = rows[k - 1][2] if k > 0 else rows[k][1]
        hi = rows[j][1] if j < len(rows) else rows[j - 1][2]
        if hi - lo > 0.5 * (j - k):
            tot = sum(nchar[k:j])
            t = lo
            for m in range(k, j):
                d = (hi - lo) * nchar[m] / tot
                rows[m] = (rows[m][0], snap_onset(t, rise) if m > k or k == 0 else t, t + d, rows[m][3])
                redistributed.append(m + 1)
                t += d
        k = j

    out = []
    for k, (i, t0, t1, sc) in enumerate(rows):
        start = max(0.0, t0 - a.lead)
        end = max(t1, start + MIN_DUR)
        if k + 1 < len(rows):
            nxt = max(0.0, rows[k + 1][1] - a.lead)
            end = min(end, nxt - 0.03) if nxt - 0.03 > start + 0.2 else end
        out.append((start, end, sc))
    for k in range(len(out) - 1):  # 起点必须单调
        if out[k + 1][0] < out[k][0] + 0.1:
            out[k + 1] = (out[k][0] + 0.1, max(out[k + 1][1], out[k][0] + 0.1 + MIN_DUR), out[k + 1][2])

    deltas = []
    for ev, (s, e, _) in zip(subs.events, out):
        deltas.append(s * 1000 - ev.start)
        ev.start, ev.end = int(s * 1000), int(e * 1000)
    subs.save(a.output)

    d = np.abs(np.array(deltas))
    report = {
        "lines": len(out),
        "realigned": len(out) - len(kept),
        "kept_original_timing": kept,
        "redistributed": redistributed,
        "start_shift_ms": {"median": int(np.median(d)), "p90": int(np.percentile(d, 90)), "max": int(d.max())},
        "lead_s": a.lead,
    }
    rp = Path(a.report or Path(a.output).with_suffix(".timing.json"))
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(out)} 句：{report['realigned']} 句按强制对齐重新定时，{len(kept)} 句置信度低保持原时间")
    print(f"起点调整幅度 中位 {report['start_shift_ms']['median']}ms / p90 {report['start_shift_ms']['p90']}ms"
          f" / 最大 {report['start_shift_ms']['max']}ms（含 {int(a.lead * 1000)}ms 提前量）")
    if kept:
        print(f"保持原时间的句子: {kept}")
    if redistributed:
        print(f"时长异常、按字数重新分配的句子: {redistributed}")
    print(f"报告: {rp}")


if __name__ == "__main__":
    main()
