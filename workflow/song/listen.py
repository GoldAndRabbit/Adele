# -*- coding: utf-8 -*-
"""第 0 步：听。

1. 找自然停顿（人声停顿、段落边界、节拍）当候选切点，每个打分；
2. 选出几组互不相同的切法（每块 25~60 s），每组识别一遍；
3. 区间重新识别（第 3 步调用）：在区间两端附近的自然停顿处切，多试几个起止，挑和该唱的歌词最像的一次。

识别模型（qwen-audio-3.1-asr-flash）的特性见方案附录 B：长段里会把含糊的一整段丢掉、对截取起止极敏感，
所以切点一定落在停顿上，几遍的切法一定互不相同。
"""

import re

import numpy as np

from workflow.live import asr_match as AM

PASSES = 4            # 几组切法（几遍识别）
CHUNK = (25.0, 60.0)  # 每块的长度范围
LENGTHS = (50.0, 38.0, 56.0, 30.0, 44.0, 34.0, 58.0)   # 每组偏好的块长，各组不同，切点自然错开
PAUSE_MIN = 0.4       # 人声停顿至少这么长才算候选切点
SECTION = 4.0         # 连续这么久没人声算段落边界
SAME_START = 10.0     # 起点相同的几段识别，起点之后这么多秒内的结果几乎一样（模型对起点极敏感），只算一票


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
        w["seg"] = [round(a, 2), round(b, 2)]   # 这个词是从哪段音频识别出来的（计票时判断几遍是不是独立）
    return ws


def independent(reads):
    """（讲话文字投票用）去掉不独立的重复：送进识别的那段音频（起点、终点）完全一样，结果就一模一样——那是同一个结果重复几次，
    不是几遍互相印证（Agua 开头第 1～4 遍挑中了同一个停顿当切点，都是 0～59.8 s，4 票「mi ya」压过了另一段听对的）。
    按顺序看每一遍，音频段和前面某一遍完全相同的，这一段的词去掉（这一遍在这里算没有证据）。
    只是起点相同、终点不同的不算重复（结果会不一样）。没有 seg 信息的词（旧缓存）原样保留。"""
    seen, out, dropped = set(), [], 0
    for ws in reads:
        keep = [w for w in ws if not (w.get("seg") and tuple(w["seg"]) in seen)]
        dropped += len(ws) - len(keep)
        out.append(keep)
        seen |= {tuple(w["seg"]) for w in ws if w.get("seg")}
    if dropped:
        print(f"计票去重：和前面某一遍音频段完全相同的 {dropped} 个词不再重复计票", flush=True)
    return out


def consensus(reads, s0, e0, gap=0.6, cap=8, latin=None):
    """一段讲话的原话按小段投票：拿词最多的那一遍按停顿（≥ gap）/ cap 个词分小段，每个小段看各遍（已去重）听到什么，
    相似的（≥ 85）算一伙，取人数最多的一伙；一样多时依次比：音频段不是刚在这里切进来的（切口后 1.5 s 常漏词）、
    听到的词多、音频段短（模型在长段里容易把含糊的话压缩、丢掉）。
    返回选中的词（带各自的时间）。"""
    from rapidfuzz import fuzz
    # 音频段完全相同的几遍只算一票（independent）；只用在这里，不动对齐用的识别结果——对齐的门槛是按「几遍互相印证」调的，
    # 整体去重会让很多地方只剩一遍证据（试过：Agua 讲话被对成了歌词）
    per = [[w for w in ws if s0 - 0.2 <= w["s"] <= e0 + 0.2] for ws in independent(reads)]
    skel = max(per, key=len)
    if not skel:
        return []
    parts, cur = [], []
    for w in skel:
        if cur and (w["s"] - cur[-1]["e"] >= gap or len(cur) >= cap):
            parts.append(cur)
            cur = []
        cur.append(w)
    parts.append(cur)
    text = lambda ws: " ".join(AM.text_of(ws).lower().split())
    span = lambda ws: min(((w["seg"][1] - w["seg"][0]) for w in ws if w.get("seg")), default=999.0)
    out = []
    for part in parts:
        a, b = part[0]["s"] - 0.15, part[-1]["e"] + 0.15
        cands = [ws for ws in ([w for w in r if a <= w["s"] <= b] for r in per) if ws]
        groups = []
        for c in cands:
            g = next((g for g in groups if fuzz.ratio(text(g[0]), text(c)) >= 85), None)
            (g.append(c) if g else groups.append([c]))
        # 刚切进来的头 1.5 s 模型常漏词（Agua 29.7 s 切进来，漏了紧接着的「y yo creo que deberíamos」）：
        # 音频段起点就在这一小段前 1.5 s 以内的算「切口」（歌曲开头从 0 切的不算，前面本来就没声音）
        clean = lambda c: all(not w.get("seg") or w["seg"][0] == 0 or w["seg"][0] <= a - 1.5 for w in c)
        # 书写系统和这首歌对不上的（西语歌里冒出一串日文假名）排最后
        script_ok = lambda c: latin is None or (not re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]", text(c))) == latin
        rank = lambda c: (script_ok(c), clean(c), len(c), -span(c))
        if not groups:
            continue
        best = max(groups, key=lambda g: (any(script_ok(c) for c in g), len(g), max(rank(c) for c in g)))
        pick = max(best, key=rank)
        if out:   # 相邻小段取自不同的识别：交界处两边都有的词只留前一段的（不然「a traer a traer」）
            pick = [w for w in pick if w["s"] >= out[-1]["e"] - 0.08]
        out += pick
    return out

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
