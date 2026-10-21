# -*- coding: utf-8 -*-
"""
全局对齐（替代 concert_align + gap_fill 的十几步修补，原因见 docs/design/alignment_root_causes.md）。

  1. 整首连续转写：人声按固定的 6 s 一块、每 3 s 一块（重叠 3 s）送 Qwen，每块只取中间 3 s 的词；
     识别文字用 MMS 在人声上逐词强制对齐，得到每个词的时间。切法固定、不依赖任何上游结果，所以结果稳定。
  2. 歌词 ↔ 转写做一次全局序列对齐（词级，读音键相似：zangalewa ≈ sangaleva）：
     顺着歌词往下唱不罚分，跳句 / 回到前面重唱 / 现场插进来的词各有罚分；括号里的和声词可以不唱。
       - 对上的歌词句：用 Genius 原句
       - 转写里连续一段没对上歌词：现场改词 / 即兴 / 喊话，按停顿切成短句，用 Qwen 的文字；
         要 2.5 s 窗口识别（另一种切法）也听到同样的词才保留，挡人群声里的幻听
       - 歌词里没对上的句子：没唱，不出字幕
  3. 声学定时（workflow/refine_timing.py 的做法）：每句 Genius 原句在「前后句之间」用 MMS 强制对齐，取首词起点 / 末词终点；
     MMS 对齐分低的句子标「声学不像」
  4. 每句统一提前 LEAD 秒出现，不压上一句
逐句 Qwen 复核（verify_qwen）在这之后只做检查、标红，不改字幕。
"""

import re

import numpy as np

CHUNK, CHUNK_HOP = 6.0, 3.0   # 长块（12 s）会把连唱两遍的句子合成一遍，短块保得住
LEAD = 0.2
HOLD = 0.4            # 句末多显示一会儿
MIN_SHOW = 0.8
PHRASE_GAP = 0.7      # 现场插进来的词：停顿超过这么久就切成下一句
MAX_PHRASE = 7
MIN_COVER = 0.5       # 一次演唱至少对上这句一半的实词（3 个字母以上；so / me 这种不算）
LOW_ACOUSTIC = 0.25   # MMS 对齐平均分低于这个：声学上不像在唱这句

# 序列对齐的分数
MATCH, MISS, INS = 3.0, 2.0, 1.0
SKIP = 1.5            # 句内漏唱一个词（括号里的和声词不罚）
EXIT_MID = 3.0        # 没唱完就离开这句
JUMP = 4.0            # 不按歌词顺序跳到别的句子（现场换序 / 重唱）
# 语气词（不含 la / na：西语冠词 la / las 会被当成语气词，配到「Ayy, yeah」上）
INTERJ = {"oh", "eh", "ah", "uh", "ay", "ayy", "aye", "hey", "ole", "oe", "yeah", "woo", "whoa", "mm",
          "hmm", "ooh", "huh", "ha", "uh-huh"}
ADJACENT = 3.0        # 纯语气词句要紧挨着真歌词（链式，间隔不超过这么多秒），否则多半是人群声
GAP_MIN = 1.5         # 这么长的空档才用声学去试「按歌词顺序该唱的句子」


def _tok(text):
    return [w for w in re.findall(r"[\w'’]+", text) if re.search(r"[^\W\d_]", w)]


# ---------------------------------------------------------------- 1. 整首连续转写 + 词级时间

INTERJ_BLOB = re.compile(r"^(?:oh|ah|eh|ay|ey|hey|ye|yeh|ya|o|a|e|y|h)+$", re.I)
INTERJ_SYL = re.compile(r"hey|oh|ah|eh|ay|ey|ye|o|a|e", re.I)


# ---------------------------------------------------------------- 2. 歌词 ↔ 转写 全局序列对齐

def lyric_tokens(lines):
    """每句的词：[(词, 是否可省略)]，括号里的（和声 / 回声）可省略。"""
    out = []
    for l in lines:
        toks = []
        for m in re.finditer(r"\(([^)]*)\)|([^()]+)", l):
            opt = m.group(1) is not None
            toks += [(w, opt) for w in _tok(m.group(1) if opt else m.group(2))]
        out.append(toks)
    return out


def similarity(trans, lyr):
    """转写词 × 歌词词 的相似度（0~1）：读音键完全一样 1，很像 0.8，词干相同 0.6；语气词只和读音相近的语气词配。"""
    from rapidfuzz import fuzz
    from rapidfuzz.process import cdist
    from .gap_fill import phon
    tp, lp = [phon(w) for w in trans], [phon(w) for w in lyr]
    r = cdist(tp, lp, scorer=fuzz.ratio, workers=-1) / 100.0
    sim = np.where(r >= 0.999, 1.0, np.where(r >= 0.8, 0.8, 0.0))
    tl, ll = [w.lower() for w in trans], [w.lower() for w in lyr]
    for i, a in enumerate(tp):
        for j, b in enumerate(lp):
            if sim[i, j] == 0 and len(a) >= 5 and len(b) >= 5 and a[:4] == b[:4]:
                sim[i, j] = 0.6
    # 语气词只和读音相近的语气词配（oh ↔ oh、ay ↔ ayy）：任意语气词都能互配的话，开场的 hey / uh huh 会被配成「Ayy, yeah」
    ti = np.array([w in INTERJ for w in tl])
    li = np.array([w in INTERJ for w in ll])
    both = np.outer(ti, li)
    sim = np.where(both & (r < 0.8), 0.0, sim)
    return sim


def decode(words, lines):
    """Viterbi：状态 = 歌词里的每个词 + 「第 L 句之后的现场插入」。返回每个转写词的去向：
    ("lyric", 句号, 词号) 或 ("ins", 前一句句号)。"""
    lt = lyric_tokens(lines)
    flat = [(L, j, w, opt) for L, toks in enumerate(lt) for j, (w, opt) in enumerate(toks)]
    S, nL, T = len(flat), len(lines), len(words)
    if not S or not T:
        return []
    line_of = np.array([f[0] for f in flat])
    pos = np.array([f[1] for f in flat])
    opt = np.array([f[3] for f in flat])
    first = np.array([j == 0 for j in pos])
    last = np.array([i == S - 1 or line_of[i + 1] != line_of[i] for i in range(S)])
    skipc = np.where(opt, 0.0, SKIP)
    # 进入第 L 句第 j 个词：前面 j 个词都算漏唱
    lead_cost = np.zeros(S)
    for i in range(S):
        if not first[i]:
            lead_cost[i] = lead_cost[i - 1] + skipc[i - 1]
    sim = similarity([w["w"] for w in words], [f[2] for f in flat])
    is_ij = np.array([w["w"].lower() in INTERJ for w in words])
    NEG = -1e9
    # 状态排布：[0, S) 歌词词；S + (L + 1) 表示第 L 句之后的插入（L = -1 是歌开始前）
    N = S + nL + 1
    ins0 = S
    prev = np.full(N, NEG)
    prev[ins0] = 0.0   # 还没开始唱
    back = np.zeros((T, N), dtype=np.int32)
    members = [np.where(line_of == L)[0] for L in range(nL)]
    for t in range(T):
        emit = np.where(sim[t] > 0, MATCH * sim[t], -MISS)
        new = np.full(N, NEG)
        arg = np.full(N, -1, dtype=np.int32)
        # 句内往下：上一个词 / 跳过一个词
        c1 = np.full(S, NEG)
        a1 = np.full(S, -1, dtype=np.int32)
        idx = np.arange(1, S)
        ok = line_of[idx] == line_of[idx - 1]
        c1[idx[ok]] = prev[idx[ok] - 1]
        a1[idx[ok]] = idx[ok] - 1
        idx2 = np.arange(2, S)
        ok2 = (line_of[idx2] == line_of[idx2 - 2])
        v2 = prev[idx2 - 2] - skipc[idx2 - 1]
        better = ok2 & (v2 > c1[idx2])
        c1[idx2[better]] = v2[better]
        a1[idx2[better]] = idx2[better] - 2
        # 离开一句的分数（唱完不罚，没唱完罚 EXIT_MID）
        exit_v = prev[:S] - np.where(last, 0.0, EXIT_MID)
        end_best = np.full(nL, NEG)
        end_arg = np.full(nL, -1, dtype=np.int32)
        for L in range(nL):
            m = members[L]
            k = m[np.argmax(exit_v[m])]
            end_best[L], end_arg[L] = exit_v[k], k
        # 每句的「从哪进来」：前一句唱完 / 前一句之后的插入 = 顺序；其他句子之后 = 跳
        src_v = np.concatenate([end_best, prev[ins0:]])      # 前 nL 个：第 L 句结束；后 nL+1 个：第 L-1 句之后的插入
        src_a = np.concatenate([end_arg, np.arange(ins0, N)])
        best_any = int(np.argmax(src_v))
        entry_v = np.full(nL, NEG)
        entry_a = np.full(nL, -1, dtype=np.int32)
        for L in range(nL):
            cands = [(src_v[best_any] - JUMP, src_a[best_any])]
            if L > 0:
                cands.append((end_best[L - 1], end_arg[L - 1]))
            cands.append((prev[ins0 + L], ins0 + L))      # 第 L-1 句之后的插入 -> 第 L 句
            v, a = max(cands, key=lambda x: x[0])
            entry_v[L], entry_a[L] = v, a
        c2 = entry_v[line_of] - lead_cost
        use_entry = c2 > c1
        best_prev = np.where(use_entry, c2, c1)
        best_arg = np.where(use_entry, entry_a[line_of], a1)
        new[:S] = best_prev + emit
        arg[:S] = best_arg
        # 插入：留在同一个插入状态，或者从第 L 句离开进入「第 L 句之后」
        ins_cost = 0.3 if is_ij[t] else INS
        for L in range(-1, nL):
            k = ins0 + L + 1
            v, a = prev[k], k
            if L >= 0 and end_best[L] > v:
                v, a = end_best[L], end_arg[L]
            new[k], arg[k] = v - ins_cost, a
        back[t] = arg
        prev = new
    # 回溯
    k = int(np.argmax(prev))
    path = [None] * T
    for t in range(T - 1, -1, -1):
        path[t] = k
        k = int(back[t, k])
    out = []
    for t, k in enumerate(path):
        if k < S:
            out.append(("lyric", int(line_of[k]), int(pos[k]), float(sim[t, k])))
        else:
            out.append(("ins", k - ins0 - 1, 0, 0.0))
    return out


def occurrences(words, path, lines):
    """把每个转写词的去向连成「某句唱了一遍」和「现场插入的一段」。"""
    lt = lyric_tokens(lines)
    items, cur = [], None
    for w, (kind, L, j, s) in zip(words, path):
        key = (kind, L)
        new_occ = cur is None or cur["key"] != key or (kind == "lyric" and j < cur["last_j"])
        if new_occ:
            cur = {"key": key, "kind": kind, "line": L, "words": [], "matched": set(), "last_j": -1}
            items.append(cur)
        cur["words"].append(w)
        if kind == "lyric":
            cur["last_j"] = j
            if s >= 0.6:
                cur["matched"].add(j)
    out = []
    for it in items:
        if it["kind"] == "lyric":
            toks = lt[it["line"]]
            pure = not [j for j, (w, opt) in enumerate(toks) if not opt and w.lower() not in INTERJ]
            need = [j for j, (w, opt) in enumerate(toks) if not opt and w.lower() not in INTERJ and len(w) >= 3] \
                or [j for j, (w, opt) in enumerate(toks) if not opt and w.lower() not in INTERJ]
            got = len([j for j in it["matched"] if j in need]) if need else len(it["matched"])
            cover = got / len(need) if need else (1.0 if got >= 2 else 0.0)
            if cover < MIN_COVER and not (len(need) == 1 and got >= 1) and not (pure and got >= 2):
                it = {**it, "kind": "ins"}   # 对不上：当成现场插入，交给后面按插入处理
            else:
                out.append({"kind": "lyric", "line": it["line"], "s": it["words"][0]["s"], "e": it["words"][-1]["e"],
                            "words": it["words"], "cover": round(cover, 2), "got": got, "need": len(need)})
                continue
        out.append({"kind": "ins", "s": it["words"][0]["s"], "e": it["words"][-1]["e"], "words": it["words"]})
    return out


# ---------------------------------------------------------------- 3. 声学定时


# ---------------------------------------------------------------- 主流程


