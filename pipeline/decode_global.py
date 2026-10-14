#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
声学为主的全局解码：直接用 MMS 对齐模型“听”整首歌，决定唱了哪些句、什么顺序、各在哪里。whisper 不参与。

1. 打分图：每句歌词 × 每个起点（0.2s 一格）× 5 种时长，算 CTC 证据
     ev = [NLL(只有 *) - NLL(* 句子 *)] / token 数      （批量计算，整首都算）
   段落得分 = (ev - θ) × token 数，θ 以下为负（不值得放字幕）
2. 全局 DP（半马尔可夫）：状态 = (时间格, 上一句)，转移先验
     顺着往下唱（含“文字相同的下一句”，处理重复副歌）  +bonus
     往后跳过若干句（删减版）                           小罚
     回跳 / 乱序（改编）                                 较大罚
   空档免费（没人唱就不放字幕），选总分最高的路径
3. 输出各句的粗定位，交给 refine_timing（强制对齐精修）+ acoustic --mode post（补空档/拖音/收尾）+ split_long

python pipeline/decode_global.py --ref ori_lyrics/X.txt --vocals separated/htdemucs/X/vocals.wav --lang en -o out.srt
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402

GRID = 0.2
MULTS = (0.6, 0.8, 1.0, 1.25, 1.6)


def score_maps(sc, texts, rate, theta, n_grid):
    """返回 S[k, u, s]：第 u 个文字、第 k 种时长、从第 s 格开始的段落得分；D[u, k] 时长（格）。"""
    em = sc.em  # (T, C) log-probs
    fr = sc.fr
    T = em.shape[0]
    U = len(texts)
    S = np.full((len(MULTS), U, n_grid + 1), -1e9, dtype=np.float32)  # 先存 ev×n，θ 之后再减
    NT = np.zeros(U, dtype=np.float32)
    D = np.zeros((U, len(MULTS)), dtype=np.int32)
    star_cache = {}

    def batched_nll(L, starts, target):
        lp = torch.stack([em[a:a + L] for a in starts], dim=1)  # (L, B, C)
        B = lp.shape[1]
        tg = torch.tensor([target] * B)
        return F.ctc_loss(lp, tg, torch.full((B,), L), torch.full((B,), len(target)), blank=0,
                          reduction="none", zero_infinity=True).numpy()

    for u, text in enumerate(texts):
        toks = sc.tokens(text)
        if not toks:
            continue
        n = len(toks)
        exp = acoustic.char_count(sc, text) * rate
        for k, m in enumerate(MULTS):
            d = int(round(min(12.0, max(0.5, exp * m)) / GRID))
            D[u, k] = d
            L = int(d * GRID * fr)
            if L < n + 2:
                continue
            grid_starts = [s for s in range(0, n_grid - d + 1) if int(s * GRID * fr) + L <= T]
            starts = [int(s * GRID * fr) for s in grid_starts]
            if not starts:
                continue
            key = L
            if key not in star_cache:
                star_cache[key] = {}
            out = np.empty(len(starts), dtype=np.float32)
            for b0 in range(0, len(starts), 512):
                chunk = starts[b0:b0 + 512]
                nl = batched_nll(L, chunk, [sc.star] + toks + [sc.star])
                ns_missing = [a for a in chunk if a not in star_cache[key]]
                if ns_missing:
                    ns = batched_nll(L, ns_missing, [sc.star])
                    star_cache[key].update(zip(ns_missing, ns))
                ns = np.array([star_cache[key][a] for a in chunk])
                out[b0:b0 + len(chunk)] = (ns - nl) / n
            S[k, u, grid_starts] = out * n
            NT[u] = n
        print(f"  打分 {u + 1}/{U}", end="\r", flush=True)
    print()
    return S, D, NT


def anchor_bonus(S, D, NT, texts, windows, n_grid, w_pos=1.5, w_neg=0.6):
    """Qwen3-ASR 滑窗锚点：段落中心落在某些窗口里，按这些窗口里“这句”的文字匹配度加分；
    窗口里明确是别的句子（某句 >=85）而这句很低（<50）时扣分。分数按 token 数缩放，和声学分同量纲。"""
    from rapidfuzz import fuzz
    from align_lyrics import reading

    W = len(windows)
    rt = [reading(t) for t in texts]
    rw = [reading(w["text"]) for w in windows]
    A = np.zeros((len(texts), W), dtype=np.float32)
    for u, r in enumerate(rt):
        for wi, x in enumerate(rw):
            A[u, wi] = fuzz.partial_ratio(r, x) if r and x else 0
    top = A.max(0) if len(texts) else np.zeros(W)
    G = n_grid + 1
    pos = np.zeros((len(texts), G), dtype=np.float32)
    neg = np.zeros((len(texts), G), dtype=np.float32)
    for g in range(G):
        c = g * GRID
        ws = [wi for wi, w in enumerate(windows) if w["start"] + 0.5 <= c <= w["end"] - 0.5 and rw[wi]]
        if not ws:
            continue
        best = A[:, ws].max(1)
        pos[:, g] = np.clip((best - 70) / 30, 0, 1)
        neg[:, g] = ((best < 50) & (top[ws].max() >= 85)).astype(np.float32)
    out = S.copy()
    for k in range(S.shape[0]):
        for u in range(S.shape[1]):
            d = D[u, k]
            if d <= 0:
                continue
            cidx = np.minimum(np.arange(G) + d // 2, G - 1)
            adj = (w_pos * pos[u, cidx] - w_neg * neg[u, cidx]) * NT[u]
            out[k, u] = np.where(S[k, u] > -1e8, S[k, u] + adj, S[k, u])
    return out


def with_theta(S, NT, theta):
    return np.where(S > -1e8, S - theta * NT[None, :, None], -1e9).astype(np.float32)


def voiced_gaps(y, segs, min_len):
    """有人声（相对 95 分位 -18dB 以上）却没被任何段落覆盖、长度 >= min_len 秒的区间。"""
    hop = 160
    k = len(y) // hop
    db = 20 * np.log10(np.sqrt((y[: k * hop].reshape(k, hop) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(25) / 25, mode="same")
    v = db > np.percentile(db, 95) - 18
    shown = np.zeros(k, bool)
    for s, t, _ in segs:
        shown[int(s * GRID * 100):int(t * GRID * 100)] = True
    g = v & ~shown
    out, i = [], 0
    while i < k:
        if g[i]:
            j = i
            while j < k and g[j]:
                j += 1
            if (j - i) / 100 >= min_len:
                out.append((i / 100, j / 100))
            i = j
        else:
            i += 1
    return out


def section_ids(path, n_lines):
    """每句所属段落实例的编号（txt 里每个 [段落] 标记开一个新段落）；srt 没有段落信息，各自成段。"""
    import re
    if Path(path).suffix.lower() != ".txt":
        return list(range(n_lines))
    ids, cur = [], 0
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if re.match(r"\s*\[", raw):
            cur += 1
            continue
        if re.sub(r"\[.*?\]", "", raw).strip():
            ids.append(cur)
    return ids[:n_lines] + [ids[-1] if ids else 0] * (n_lines - len(ids))


def transition_matrix(texts_of_line, b_next=1.5, strict=False, seg_cost=1.0, sections=None, skip_cost=0.3):
    """strict：参考歌词就是这一版的演唱顺序（如官方字幕）——回跳/重复重罚。
    seg_cost：每多放一句的固定代价，防止证据一般的位置被反复插句。"""
    N = len(texts_of_line)
    tr = np.full((N, N), -2.0, dtype=np.float32)
    for i in range(N):
        nxt = texts_of_line[i + 1] if i + 1 < N else None
        for j in range(N):
            # 严格模式：参考本身就是演唱序列（含重复副歌的每一遍），只有紧接的下一句算“顺着唱”；
            # 宽松模式：文字相同的“下一句”也算（参考里副歌只写一遍、实际唱多遍）
            if j == i + 1 or (not strict and nxt is not None and texts_of_line[j] == nxt):
                tr[i, j] = b_next                     # 顺着往下（或文字相同的“下一句”）
            elif j > i + 1:
                if sections is None:
                    tr[i, j] = -skip_cost * min(j - i - 1, 10)
                else:
                    # 现场删减一般是整段删：跳过整段便宜，跳过段落中间的句子贵
                    skipped = range(i + 1, j)
                    mid = sum(1 for m in skipped if sections[m] in (sections[i], sections[j]))
                    whole = len({sections[m] for m in skipped} - {sections[i], sections[j]})
                    tr[i, j] = -2.5 * mid - 0.4 * whole
            elif j == i:
                tr[i, j] = -6.0 if strict else -0.5   # 同一句连唱
            else:
                tr[i, j] = -8.0 if strict else -2.0   # 回跳 / 乱序（改编）
    return tr - seg_cost


def decode(S, D, line_text_id, tr, allow=None):
    """allow: (N, G+1) 布尔矩阵，第 j 句只能从允许的格子起唱（来自 Qwen 分块时间），None 表示不限。"""
    K, U, G1 = S.shape
    G = G1 - 1
    N = len(line_text_id)
    start = np.array([-0.05 * j for j in range(N)], dtype=np.float32)
    best = np.full((G + 1, N), -1e9, dtype=np.float32)
    bp_d = np.zeros((G + 1, N), dtype=np.int16)    # 0 = 从 t-1 延续（空档）
    bp_i = np.full((G + 1, N), -1, dtype=np.int32)  # 上一句；-1 = 开头
    M = np.full((G + 1, N), -1e9, dtype=np.float32)
    Mi = np.full((G + 1, N), -1, dtype=np.int32)
    Sl = S[:, line_text_id, :].copy()  # (K, N, G+1)
    if allow is not None:
        Sl[:, ~allow] = -1e9
    Dl = D[line_text_id, :]          # (N, K)
    ar = np.arange(N)

    def finalize(s):
        cand = best[s][:, None] + tr                     # (i, j)
        i_best = cand.argmax(0)
        v = cand[i_best, ar]
        use_start = start >= v
        M[s] = np.where(use_start, start, v)
        Mi[s] = np.where(use_start, -1, i_best)

    finalize(0)
    for t in range(1, G + 1):
        cur = best[t - 1].copy()
        cd = np.zeros(N, dtype=np.int16)
        ci = bp_i[t - 1].copy()
        for k in range(K):
            d = Dl[:, k]
            s = t - d
            ok = (d > 0) & (s >= 0)
            if not ok.any():
                continue
            sv = np.where(ok, s, 0)
            val = M[sv, ar] + Sl[k, ar, sv]
            val = np.where(ok, val, -1e9)
            better = val > cur
            cur = np.where(better, val, cur)
            cd = np.where(better, d, cd)
            ci = np.where(better, Mi[sv, ar], ci)
        best[t], bp_d[t], bp_i[t] = cur, cd, ci
        finalize(t)

    # 回溯
    segs = []
    t, j = G, int(best[G].argmax())
    while t > 0 and j >= 0:
        d = int(bp_d[t, j])
        if d == 0:
            t -= 1
            continue
        s = t - d
        segs.append((s, t, j))
        j = int(bp_i[t, j])
        t = s
        # 回到 s 格时的状态是“上一句 = j”，继续回溯
    return list(reversed(segs)), float(best[G].max())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", required=True, help="参考歌词 txt（可带 [段落]）或官方字幕 srt")
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--rate", type=float, default=None, help="每个字母/假名的平均演唱时长（秒），默认用 --rate-from 估计")
    p.add_argument("--rate-from", help="已有字幕，用来估计演唱速率")
    p.add_argument("--theta", type=float, default=-4.0, help="声学证据门槛，低于它的位置不值得放字幕")
    p.add_argument("--relax-theta", type=float, default=-4.6,
                   help="第二遍补空档用的放宽门槛（只作用于严格解码后长时间有人声没字幕的地方）；设为空可关闭")
    p.add_argument("--strict-order", type=lambda v: v.lower() in ("1", "true", "yes"), default=None,
                   help="参考歌词是否就是演唱顺序；默认：官方字幕(srt)=是，歌词 txt=否")
    p.add_argument("--anchors", help="qwen_asr.py 产出的滑窗识别结果 json，作为结构锚点")
    p.add_argument("--anchor-w", type=float, default=1.5, help="锚点加分（每 token）")
    p.add_argument("--anchor-neg", type=float, default=0.6, help="锚点明确否定时扣分（每 token）")
    p.add_argument("--section-skip", action="store_true", help="实验：按 [段落] 整段跳过便宜、段中跳句贵")
    p.add_argument("--windows", help="qwen_sequence.py 的报告 json（chunks），给每句加时间范围约束")
    p.add_argument("--window-pad", type=float, default=2.0)
    p.add_argument("--skip-cost", type=float, default=0.3,
                   help="每跳过一句的代价；参考是 Qwen 确认过的演唱序列时调高（如 6），强制每句都找位置")
    p.add_argument("--seg-cost", type=float, default=1.0, help="每多放一句的固定代价")
    p.add_argument("--gap-min", type=float, default=2.0, help="多长的有声空档才做第二遍")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    a = p.parse_args()

    import pysubs2
    sc = acoustic.Scorer(a.vocals, a.lang)
    lines = [t for t, _ in acoustic.section_lines(a.ref)]
    if a.rate:
        rate = a.rate
    elif a.rate_from:
        ev = pysubs2.load(a.rate_from).events
        rate = float(np.median([(e.end - e.start) / 1000 / acoustic.char_count(sc, e.plaintext) for e in ev]))
    else:
        rate = 0.12
    texts = sorted(set(lines), key=lines.index)
    tid = {t: i for i, t in enumerate(texts)}
    line_text_id = np.array([tid[t] for t in lines])
    n_grid = int(len(sc.y) / acoustic.SR / GRID)
    print(f"{len(lines)} 句（{len(texts)} 种文字），{n_grid} 格，速率 {rate:.3f}s/字，θ={a.theta}")

    S_raw, D, NT = score_maps(sc, texts, rate, a.theta, n_grid)
    if a.anchors and Path(a.anchors).exists():
        wins = json.loads(Path(a.anchors).read_text())["windows"]
        S_raw = anchor_bonus(S_raw, D, NT, texts, wins, n_grid, a.anchor_w, a.anchor_neg)
        print(f"Qwen3-ASR 锚点: {len(wins)} 个窗口，权重 +{a.anchor_w}/-{a.anchor_neg}")
    strict = a.strict_order if a.strict_order is not None else Path(a.ref).suffix.lower() in (".srt", ".ass", ".vtt")
    # 段落感知的跳过罚分：HKT48 上实测让顺序更乱，默认关闭
    sections = section_ids(a.ref, len(lines)) if a.section_skip else None
    tr = transition_matrix(lines, strict=strict, seg_cost=a.seg_cost, sections=sections, skip_cost=a.skip_cost)
    print(f"顺序约束: {'严格（参考即演唱顺序）' if strict else '宽松（允许跳过/重复/乱序）'}，每句代价 {a.seg_cost}")
    allow = None
    if a.windows:
        chunks = json.loads(Path(a.windows).read_text())["chunks"]
        spans = [(c["start"], c["end"]) for c in chunks for _ in c["lines"]]
        if len(spans) != len(lines):
            sys.exit(f"--windows 里的句数 {len(spans)} 和参考 {len(lines)} 对不上")
        allow = np.zeros((len(lines), n_grid + 1), dtype=bool)
        for j, (t0, t1) in enumerate(spans):
            allow[j, max(0, int((t0 - a.window_pad) / GRID)):min(n_grid + 1, int((t1 + a.window_pad) / GRID) + 1)] = True
        print(f"Qwen 分块时间约束: 每句只能在所在块 ±{a.window_pad}s 内")
    segs, total = decode(with_theta(S_raw, NT, a.theta), D, line_text_id, tr, allow)
    # 第二遍：严格门槛定结构；只在“长时间有人声却没字幕”的空档里，用放宽的门槛补句
    added = 0
    if a.relax_theta is not None:
        gaps = voiced_gaps(sc.y, segs, a.gap_min)
        if gaps:
            relaxed, _ = decode(with_theta(S_raw, NT, a.relax_theta), D, line_text_id, tr, allow)
            for s, t, j in relaxed:
                a0, a1 = s * GRID, t * GRID
                inside = max((min(a1, g1) - max(a0, g0) for g0, g1 in gaps), default=0)
                no_clash = all(t <= s2 or s >= t2 for s2, t2, _ in segs)
                if inside >= 0.8 * (a1 - a0) and no_clash:
                    segs.append((s, t, j))
                    added += 1
            segs.sort()
        print(f"严格解码后有人声没字幕的空档 {len(gaps)} 段；放宽门槛补入 {added} 句")

    res = pysubs2.SSAFile()
    order = []
    for s, t, j in segs:
        res.events.append(pysubs2.SSAEvent(start=int(s * GRID * 1000), end=int(t * GRID * 1000), text=lines[j]))
        order.append(j + 1)
    res.save(a.output)
    rep = {"lines_out": len(segs), "reference_lines": len(lines), "rate": rate, "theta": a.theta,
           "order": order, "skipped_reference_lines": sorted(set(range(1, len(lines) + 1)) - set(order)),
           "score": total}
    if a.report:
        Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n")
    print(f"解码出 {len(segs)} 句；参考歌词里没被选中的 {len(rep['skipped_reference_lines'])} 句；顺序：{order}")


if __name__ == "__main__":
    main()
