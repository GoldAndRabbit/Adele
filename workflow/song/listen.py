# -*- coding: utf-8 -*-
"""第 0 步：听。

1. 找自然停顿（人声停顿、段落边界、节拍）当候选切点，每个打分；
2. 选出几组互不相同的切法（每块 25~60 s），每组识别一遍；
3. 区间重新识别（第 3 步调用）：在区间两端附近的自然停顿处切，多试几个起止，挑和该唱的歌词最像的一次。

识别模型（qwen-audio-3.1-asr-flash）的特性见方案附录 B：长段里会把含糊的一整段丢掉、对截取起止极敏感，
所以切点一定落在停顿上，几遍的切法一定互不相同。
"""

import numpy as np

from workflow.live import asr_match as AM

PASSES = 4            # 几组切法（几遍识别）
CHUNK = (25.0, 60.0)  # 每块的长度范围
LENGTHS = (50.0, 38.0, 56.0, 30.0, 44.0, 34.0, 58.0)   # 每组偏好的块长，各组不同，切点自然错开
PAUSE_MIN = 0.4       # 人声停顿至少这么长才算候选切点
SECTION = 4.0         # 连续这么久没人声算段落边界


def pauses(y, sr, pitch, beats=None):
    """候选切点 [(时间, 分)]：人声能量低、且音高曲线显示没在发声，持续 ≥ PAUSE_MIN。
    分 = 停顿长度（段落边界最高）+ 靠近节拍的小加分。"""
    hop = sr // 100
    k = min(len(y) // hop, len(pitch.voiced))
    rms = np.sqrt((y[:k * hop].reshape(k, hop) ** 2).mean(1))
    ref = np.percentile(rms[rms > 1e-4], 75) if (rms > 1e-4).any() else 1.0
    quiet = (rms < 0.15 * ref) & ~pitch.voiced[:k]
    out, i = [], 0
    while i < k:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < k and quiet[j]:
            j += 1
        n = (j - i) / 100
        if n >= PAUSE_MIN:
            t = (i + j) / 200
            score = min(n, SECTION) / SECTION + (1.0 if n >= SECTION else 0.0)
            if beats is not None and len(beats):
                score += 0.2 * float(np.min(np.abs(beats - t)) < 0.15)
            # 段落边界：切在停顿结束前 0.3 s（贴着下一句开头，上下文从下一句开始）
            out.append((round(j / 100 - 0.3 if n >= SECTION else t, 2), round(score, 3)))
        i = j
    return out


def cut_sets(cands, dur, n=PASSES):
    """n 组互不相同的切法。每组从头往后：在 [t+25, t+60] 的候选切点里挑「分高、接近本组偏好块长、前面几组没用过」的。"""
    sets, used = [], []
    for g in range(n):
        want = LENGTHS[g % len(LENGTHS)]
        cuts, t = [], 0.0
        while dur - t > CHUNK[1]:
            win = [(c, s) for c, s in cands if t + CHUNK[0] <= c <= t + CHUNK[1]]
            if win:
                def value(cs):
                    c, s = cs
                    reuse = any(abs(c - u) < 2.0 for u in used)
                    return s - (0.8 if reuse else 0.0) - 0.015 * abs((c - t) - want)
                c = max(win, key=value)[0]
            else:
                c = t + want   # 没有停顿（一直在唱）：只能硬切
            cuts.append(round(c, 2))
            t = c
        used += cuts
        edges = [0.0] + cuts + [dur]
        sets.append(list(zip(edges, edges[1:])))
    return sets


MAX_WPS = 20.0   # 识别结果的语速上限（词/秒，按 10 s 一格算）：正常演唱最快约 10（Waka Waka 口号段），
                 # 识别卡进循环时会到 100 以上（Lorde Broken Glass 第 2 遍：40 s 里同一段副歌重复了 2600 多个词）


def recognize(y, sr, key, cache, a, b, src):
    ws = AM.asr_words(y[int(a * sr):int(b * sr)], sr, key, cache, t0=a)
    ws = [w for w in ws if a - 0.5 <= w["s"] <= b + 0.5]   # 时间落在这段音频外面的：识别错了
    bins = {}
    for w in ws:
        bins[int(w["s"] // 10)] = bins.get(int(w["s"] // 10), 0) + 1
    if bins and max(bins.values()) > MAX_WPS * 10:
        print(f"识别结果不可信（{a:.0f}-{b:.0f}s 有 10 s 里 {max(bins.values())} 个词，第 {src} 遍）：这一段这遍不用", flush=True)
        return []
    for w in ws:
        w["src"] = src
    return ws


def listen(y, sr, key, cache, pitch, beats=None, n=PASSES):
    """n 遍识别（切法互不相同）。返回 (reads, cands, sets)。"""
    dur = len(y) / sr
    cands = pauses(y, sr, pitch, beats)
    sets = cut_sets(cands, dur, n)
    reads = []
    for g, chunks in enumerate(sets, 1):
        ws = []
        for a, b in chunks:
            ws += recognize(y, sr, key, cache, a, b, g)
        reads.append(ws)
    return reads, cands, sets


def relisten(y, sr, key, cache, cands, a, b, judge, src, tries=6):
    """区间 [a, b] 重新识别：起止取 a 之前 / b 之后最近的几个自然停顿（没有就前后各让 2~6 s），
    每种组合识别一次，用 judge(words) 打分，返回最高分的那次（只保留区间里的词）。"""
    dur = len(y) / sr
    left = sorted([c for c, _ in cands if a - 8 <= c <= a], reverse=True)[:3] or [max(0.0, a - 2)]
    right = sorted([c for c, _ in cands if b <= c <= b + 8])[:3] or [min(dur, b + 2)]
    left += [max(0.0, a - 4), max(0.0, a - 6)]
    right += [min(dur, b + 4), min(dur, b + 6)]
    combos, seen = [], set()
    for x0 in left:
        for x1 in right:
            k = (round(x0, 1), round(x1, 1))
            if k not in seen and 2.0 <= x1 - x0 <= 45.0:
                seen.add(k)
                combos.append(k)
    best = (0.0, [])
    for x0, x1 in combos[:tries]:
        ws = [w for w in recognize(y, sr, key, cache, x0, x1, src) if a - 0.3 <= w["s"] < b + 0.3]
        sc = judge(ws)
        if sc > best[0]:
            best = (sc, ws)
    return best[1]
