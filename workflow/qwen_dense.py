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
MIN_COVER = float(os.environ.get("DENSE_MIN_COVER", 0.15))  # 窗口识别文字至少这么多落在匹配的这句上
MIN_WINDOWS = int(os.environ.get("DENSE_MIN_WINDOWS", 2))  # 一句至少连续命中 2 个窗口才算唱了（孤立命中多半是说话/喊话里的巧合）


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


def order_align(starts, texts, lines, ur, fuzz, skip_pen=300.0):
    """尊重歌词：参考歌词按顺序逐句往下走（单调对齐），每句都必须放上，窗口识别只当时间证据。
    dp[w][j]：前 w 个窗口用完、当前停在第 j 句。每个窗口要么归给当前句（得分 = 匹配度 - 50），
    要么归给下一句、要么空着（0 分，句间停顿/间奏）；跳过一句罚 skip_pen。"""
    from textnorm import reading
    W, L = len(starts), len(lines)
    rr = [reading(x) for x in texts]
    S = np.zeros((W, L), dtype=np.float32)
    for w in range(W):
        if len(rr[w]) < 4:
            continue
        for j, l in enumerate(lines):
            u = ur.get(l) or reading(l)
            if len(u) >= 3:
                S[w, j] = fuzz.partial_ratio(u, rr[w]) - 50
    NEG = -1e9
    dp = np.full((W + 1, L + 1), NEG, dtype=np.float64)
    bp = np.zeros((W + 1, L + 1), dtype=np.int16)   # 0 空窗, 1 留在当前句, 2 进入新句(从 j-1), 3 跳句
    dp[0, 0] = 0.0
    for w in range(1, W + 1):
        for j in range(0, L + 1):
            best, how = dp[w - 1, j], 0                       # 空窗
            if j >= 1:
                v = dp[w - 1, j] + S[w - 1, j - 1]            # 继续唱第 j 句
                if v > best:
                    best, how = v, 1
                v = dp[w - 1, j - 1] + S[w - 1, j - 1]        # 开始唱第 j 句
                if v > best:
                    best, how = v, 2
            dp[w, j] = best
            bp[w, j] = how
        for j in range(1, L + 1):                             # 跳过第 j 句（罚分，尽量不跳）
            v = dp[w, j - 1] - skip_pen
            if v > dp[w, j]:
                dp[w, j], bp[w, j] = v, 3
    # 回溯：每句分到的窗口
    span = {j: [] for j in range(1, L + 1)}
    w, j = W, L
    while w > 0 or j > 0:
        how = bp[w, j]
        if how == 3:
            j -= 1
            continue
        if w == 0:
            j -= 1
            continue
        if how in (1, 2):
            span[j].append(w - 1)
        if how == 2:
            j -= 1
        w -= 1
    runs = []
    for j in range(1, L + 1):
        # 时间只用“确实像在唱这句”的窗口来定（匹配度 >= 75），弱匹配窗口只保证顺序，不拉长这句
        strong = sorted(w for w in span[j] if S[w, j - 1] >= MIN_SCORE - 50)
        # 强匹配窗口如果断成几簇（中间隔 >2s），取证据最多的一簇；不让一句横跨一大段
        clusters, cur = [], []
        for w in strong:
            if cur and (w - cur[-1]) * HOP > 2.0:
                clusters.append(cur)
                cur = []
            cur.append(w)
        if cur:
            clusters.append(cur)
        ws = max(clusters, key=lambda c: sum(S[x, j - 1] for x in c)) if clusters else []
        runs.append([starts[min(ws)], starts[max(ws)] + WIN, lines[j - 1]] if ws else [None, None, lines[j - 1]])
    # 没分到窗口的句子：在前后句之间按字数插值（每句都要显示）
    for k, r in enumerate(runs):
        if r[0] is None:
            lo = next((runs[i][1] for i in range(k - 1, -1, -1) if runs[i][0] is not None), 0.0)
            hi = next((runs[i][0] for i in range(k + 1, len(runs)) if runs[i][0] is not None), lo + 3.0)
            r[0], r[1] = lo, max(lo + 0.8, min(hi, lo + 3.0))
    # 保证顺序和不重叠，且每句至少显示 0.8s（歌词一句都不丢）
    for k in range(1, len(runs)):
        if runs[k][0] < runs[k - 1][0] + 0.8:
            runs[k][0] = runs[k - 1][0] + 0.8
        runs[k][1] = max(runs[k][1], runs[k][0] + 0.8)
    for x, z in zip(runs, runs[1:]):
        if z[0] < x[1]:
            x[1] = z[0] - 0.02
    return runs


def section_align(starts, texts, sections, ur, fuzz, skip_pen=300.0, jump_pen=30.0):
    """按段落尊重歌词：段内严格按歌词顺序（不许跳句，跳一句罚 skip_pen），段与段之间可以按现场顺序跳转/重复
    （进入任意一段的开头罚 jump_pen）。sections = [[段内各句文字], ...]，内容相同的段只保留一份。
    返回按演唱时间排列的 [start, end, text]，每次进入的段落都完整输出（没证据的句子插值）。"""
    from textnorm import reading
    uniq_secs = []
    for sec in sections:
        if sec not in uniq_secs:
            uniq_secs.append(sec)
    states = [(k, i, t) for k, sec in enumerate(uniq_secs) for i, t in enumerate(sec)]
    N, W = len(states), len(starts)
    first = np.array([i == 0 for _, i, _ in states])
    last = np.array([i == len(uniq_secs[k]) - 1 for k, i, _ in states])
    rr = [reading(x) for x in texts]
    S = np.zeros((W, N), dtype=np.float32)
    for w in range(W):
        if len(rr[w]) < 4:
            continue
        for n, (_, _, t) in enumerate(states):
            u = ur.get(t) or reading(t)
            if len(u) >= 3:
                S[w, n] = fuzz.partial_ratio(u, rr[w]) - 50
    NEG = -1e18
    # 虚拟状态 N = “段与段之间 / 开头”
    dp = np.full(N + 1, NEG)
    dp[N] = 0.0
    hist = np.zeros((W, N + 1), dtype=np.int32)  # 来源状态；-1 = 停留（空窗或继续同一句）
    for w in range(W):
        new = np.full(N + 1, NEG)
        src = np.full(N + 1, -1, dtype=np.int32)
        # 停留：空窗（不加分）或继续唱同一句（加分）
        new[:N] = dp[:N] + np.maximum(S[w], 0.0)
        new[N] = dp[N]
        # 段落结束 -> 段间
        end_best = np.max(np.where(last, dp[:N], NEG))
        if end_best > new[N]:
            new[N] = end_best
            src[N] = int(np.argmax(np.where(last, dp[:N], NEG)))
        for n in range(N):
            k, i, _ = states[n]
            cands = []
            if first[n]:
                cands.append((dp[N] - jump_pen, N))                    # 段间 -> 进入一段
            if i >= 1:
                cands.append((dp[n - 1], n - 1))                      # 段内下一句
            if i >= 2:
                cands.append((dp[n - 2] - skip_pen, n - 2))           # 段内跳一句（重罚）
            for v, f in cands:
                v = v + S[w, n]
                if v > new[n]:
                    new[n], src[n] = v, f
        dp = new
        hist[w] = src
    # 回溯
    n = int(np.argmax(np.where(np.append(last, True), dp, NEG)))
    assign = [None] * W   # 每个窗口所在状态（None = 段间）
    enter = [False] * W   # 这个窗口是否“新进入”这一句
    skipped = {}          # 窗口 w 进入 n 时跳过的句子
    for w in range(W - 1, -1, -1):
        f = hist[w, n]
        assign[w] = None if n == N else n
        if f != -1:
            enter[w] = True
            if n < N and f < N and f == n - 2:
                skipped[w] = n - 1
            n = f
    # 每次进入一句 = 一次演唱；用这次演唱里的强匹配窗口定时间
    runs, w = [], 0
    while w < W:
        n = assign[w]
        if n is None:
            w += 1
            continue
        j = w
        while j + 1 < W and assign[j + 1] == n and not enter[j + 1]:
            j += 1
        strong = [x for x in range(w, j + 1) if S[x, n] >= MIN_SCORE - 50]
        ws = strong or list(range(w, j + 1))
        if w in skipped:
            runs.append([None, None, states[skipped[w]][2], states[skipped[w]][0], False])
        runs.append([starts[min(ws)], starts[max(ws)] + WIN, states[n][2], states[n][0], bool(strong)])
        w = j + 1
    # 一次段落演唱里，被识别证实的句子不到 30%：多半是说话/喊话被误配，整段不算
    kept, k = [], 0
    while k < len(runs):
        m = k
        while m + 1 < len(runs) and runs[m + 1][3] == runs[k][3]:
            m += 1
        grp = runs[k:m + 1]
        if sum(1 for r in grp if r[4]) >= 0.3 * len(grp):
            kept.extend(grp)
        k = m + 1
    runs = [r[:3] for r in kept]
    # 单句显示时长上限：按字数估算（每字约 0.07s）的 2.5 倍，最长 8s；挂太久的截掉尾巴
    for r in runs:
        if r[0] is not None:
            cap = min(8.0, max(2.0, len(r[2]) * 0.07 * 2.5))
            r[1] = min(r[1], r[0] + cap)
    for k, r in enumerate(runs):
        if r[0] is None:
            lo = next((runs[i][1] for i in range(k - 1, -1, -1) if runs[i][0] is not None), 0.0)
            hi = next((runs[i][0] for i in range(k + 1, len(runs)) if runs[i][0] is not None), lo + 3.0)
            r[0], r[1] = lo, max(lo + 0.8, min(hi, lo + 3.0))
    for k in range(1, len(runs)):
        if runs[k][0] < runs[k - 1][0] + 0.8:
            runs[k][0] = runs[k - 1][0] + 0.8
        runs[k][1] = max(runs[k][1], runs[k][0] + 0.8)
    for x, z in zip(runs, runs[1:]):
        if z[0] < x[1]:
            x[1] = z[0] - 0.02
    return runs


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--sections", help="带 [段落] 标记的歌词（--keep-sections 抓的），--order sections 用")
    p.add_argument("--order", choices=["sections", "lyrics", "free"], default="lyrics",
                   help="lyrics（默认）：按歌词顺序逐句单调对齐，每句都放上；free：每窗独立匹配（可乱序，会漏句）")
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
        cand = []
        for u in uniq:
            if len(ur[u]) < 6:
                continue
            al = fuzz.partial_ratio_alignment(ur[u], r)
            if not al or al.score < MIN_SCORE:
                continue
            # 窗口里识别出的文字，大部分要落在这句歌词上：说话里偶然出现几个像歌词的词不算在唱
            cover = (al.dest_end - al.dest_start) / len(r)
            if cover >= MIN_COVER:
                cand.append((al.score, u))
        best.append(max(cand)[1] if cand else None)

    if a.order == "sections":
        import itertools
        secs = [[t for t, _ in grp] for _, grp in itertools.groupby(acoustic.section_lines(a.sections), key=lambda x: x[1])]
        runs = section_align(starts, texts, secs, ur, fuzz)
        if a.tighten:
            runs = tighten(runs, y, a.lang)
        subs = pysubs2.SSAFile()
        for s_, e_, t in runs:
            subs.events.append(pysubs2.SSAEvent(start=int(s_ * 1000), end=int(e_ * 1000), text=t))
        subs.save(a.output)
        print(f"按段落对齐：{len(secs)} 段，输出 {len(runs)} 句")
        return
    if a.order == "lyrics":
        runs = order_align(starts, texts, lines, ur, fuzz)
        if a.tighten:
            runs = tighten(runs, y, a.lang)
        subs = pysubs2.SSAFile()
        for s_, e_, t in runs:
            subs.events.append(pysubs2.SSAEvent(start=int(s_ * 1000), end=int(e_ * 1000), text=t))
        subs.save(a.output)
        print(f"歌词顺序对齐：参考 {len(lines)} 句全部定位（{len(starts)} 窗证据）")
        return

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
        if sum(1 for b in best[i:last + 1] if b == txt) >= MIN_WINDOWS:
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
