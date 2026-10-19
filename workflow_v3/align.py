# -*- coding: utf-8 -*-
"""第 1~2 步：整首顺序对齐（词级动态规划）+ 锚点。

Genius 侧：整首歌词按顺序展开成「读音单元」（拉丁字母一个词一个单元，日中韩一个假名 / 字一个单元）。
识别侧：几遍识别的所有词，按时间合成一个词网格（同一时刻不同遍听到的不同词都是候选，记下几遍支持）。
对齐：一次动态规划，状态 =「Genius 第 t 个单元」，每个识别单元要么对上一个 Genius 单元，要么算歌词外（插入）。
跳转（全部歌曲共用的几个代价）：
    同一行下一个单元 0；跳过一个单元 DEL（括号里的和声、语气词 0）；
    行尾 → 下一行 0；→ 本行（唱两遍）REP；→ 前面任意一行（副歌再唱）BACK；→ 后面隔了几行 SKIP × 行数（封顶 FAR）；
    歌词开始前 → 任意一行 START；歌词外（每个识别单元）INS。
"""

import re
from functools import lru_cache

import numpy as np

from workflow_v2.align4 import INTERJ, line_lang, script_of

# ---------------------------------------------------------------- 参数（全部歌曲共用）
TAU = 0.6     # 读音相似度高于这个才算「对上」有正分
INS = 0.3     # 一个识别单元算歌词外的代价
DEL = 0.15    # 跳过一个 Genius 单元（没唱 / 没听到）
EXIT = 0.6    # 一行没唱完就离开，最多扣这么多
REP = 0.3     # 一句唱两遍
BACK = 0.8    # 跳回前面某一行（副歌再唱、换序）
SKIP = 0.25   # 往后跳过一行
FAR = 1.2     # 往后跳很多行，最多扣这么多
START = 0.2   # 从歌词开始前进入某一行
START_STEP = 0.005  # 进入第 k 行再加 k × 这么多
ANCHOR = 0.45  # 锚点置信度阈值
STRAY_GAP = 2.5  # 一行里停顿超过这么久、后面只跟着一个单元：那个单元不算这一行

KANA = re.compile(r"[぀-ヿ]")
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
ALL_INTERJ = set().union(*INTERJ.values()) | {"uh", "oh", "ah", "eh", "na", "la", "mm", "ooh", "woo", "yeah"}


# ---------------------------------------------------------------- 读音单元

def _phon(w):
    from workflow_v2.gap_fill import phon
    return phon(w)


@lru_cache(maxsize=4096)
def _hira(text):
    """日文 / 汉字 -> 平假名串（片假名转平假名、去长音、去标点）。"""
    import pykakasi
    out = []
    for seg in pykakasi.kakasi().convert(text):
        out.append((seg["orig"], seg["hira"]))
    return out


def _norm_kana(s):
    s = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)
    return re.sub(r"[ー〜~・\s]", "", s)


def tokens(text):
    """一段文字 -> 读音单元 [(key, kind, 起, 止, 可选)]；起止是在原文里的字符位置（显示半句时用）。
    kind：'w' 拉丁词，'k' 假名 / 字。括号里的（和声）、纯语气词标为可选。"""
    out = []
    paren = [(m.start(), m.end()) for m in re.finditer(r"\([^)]*\)", text)]

    def opt_at(i):
        return any(a <= i < b for a, b in paren)
    if CJK.search(text):
        pos = 0
        for orig, hira in _hira(text):
            i = text.find(orig, pos) if orig else pos
            i = pos if i < 0 else i
            j = i + len(orig)
            pos = j
            if re.search(r"[A-Za-z]", orig) and not CJK.search(orig):
                for m in re.finditer(r"[A-Za-z]+(?:['’][A-Za-z]+)?", orig):
                    w = m.group(0)
                    k = _phon(w)
                    if k:
                        out.append((k, "w", i + m.start(), i + m.end(), opt_at(i) or w.lower() in ALL_INTERJ))
                continue
            kana = _norm_kana(hira if CJK.search(orig) else orig)
            kana = re.sub(r"[^぀-ゟ㐀-鿿가-힯]", "", kana)
            for c in kana:
                out.append((c, "k", i, j, opt_at(i)))
        return out
    for m in re.finditer(r"[^\W\d_]+(?:['’][^\W\d_]+)*", text):
        w = m.group(0)
        parts = [p for p in w.lower().split("-") if p]
        k = _phon(w)
        if k:
            out.append((k, "w", m.start(), m.end(), opt_at(m.start()) or (parts and all(p in ALL_INTERJ for p in parts))))
    for m in re.finditer(r"[^\W\d_]+(?:-[^\W\d_]+)+", text):   # Oh-eh-oh-eh 这类连写的语气词整体可选
        pass
    return out


def sim(a, b):
    """两个读音单元的相似度 0~1。"""
    if a[1] != b[1]:
        return 0.0
    if a[1] == "k":
        return 1.0 if a[0] == b[0] else 0.0
    if len(a[0]) <= 2 or len(b[0]) <= 2:
        return 1.0 if a[0] == b[0] else 0.0
    from rapidfuzz import fuzz
    return fuzz.ratio(a[0], b[0]) / 100


# ---------------------------------------------------------------- Genius 侧

class Lyrics:
    def __init__(self, lines):
        from workflow_v2.gap_fill import clean_parens
        self.lines = lines
        self.plain = [clean_parens(l) or l for l in lines]
        main = line_lang(" ".join(lines))
        self.langs = [line_lang(l, main) for l in lines]
        self.main = max(set(self.langs), key=self.langs.count) if lines else "en"
        self.tok, self.line_of, self.start, self.end = [], [], [], []
        for k, l in enumerate(lines):
            ts = tokens(l) or [("", "w", 0, len(l), True)]
            self.start.append(len(self.tok))
            self.tok += ts
            self.line_of += [k] * len(ts)
            self.end.append(len(self.tok))
        self.T = len(self.tok)
        self.opt = np.array([t[4] for t in self.tok], bool)
        self.skipc = np.where(self.opt, 0.0, DEL)
        # 唯一度：同一句（读音一样）在 Genius 里出现几次
        keys = [" ".join(t[0] for t in self.tok[self.start[k]:self.end[k]] if not t[4]) for k in range(len(lines))]
        self.dups = [keys.count(x) for x in keys]
        self.key = keys


# ---------------------------------------------------------------- 识别侧：词网格

def units_of(ws):
    """识别词 -> 读音单元（日文一个分块拆成几个假名，时间均分）。"""
    out = []
    for w in ws:
        ts = tokens(w["w"])
        if not ts:
            continue
        n = len(ts)
        for i, t in enumerate(ts):
            s = w["s"] + (w["e"] - w["s"]) * i / n
            e = w["s"] + (w["e"] - w["s"]) * (i + 1) / n
            out.append({"key": t[0], "kind": t[1], "s": s, "e": e, "src": w["src"], "surf": w["w"], "wid": id(w)})
    return out


def lattice(reads):
    """几遍识别 -> 按时间排序的网格单元。每个单元：几个候选（读音、支持的遍、各遍的起止、原文）。"""
    us = sorted((u for ws in reads for u in units_of(ws)), key=lambda u: (u["s"], u["src"]))
    cells = []
    for u in us:
        attach = None
        mid = (u["s"] + u["e"]) / 2
        # 先找附近读音一样的（各遍分块不同，同一个字的时间会差一些：日文 0.8 s、拉丁词 0.5 s 内算同一个）
        tol = 0.8 if u["kind"] == "k" else 0.5
        for c in reversed(cells[-24:]):
            if u["src"] in c["srcs"] or abs(mid - (c["s"] + c["e"]) / 2) > tol:
                continue
            if any(sim((cd["key"], cd["kind"]), (u["key"], u["kind"])) >= 0.8 for cd in c["cands"]):
                attach = c
                break
        if attach is None:
            for c in reversed(cells[-8:]):
                if u["src"] in c["srcs"]:
                    continue
                cmid = (c["s"] + c["e"]) / 2
                if abs(mid - cmid) <= max(0.3, (c["e"] - c["s"]) / 2):
                    attach = c
                    break
        if attach is None:
            attach = {"s": u["s"], "e": u["e"], "srcs": set(), "cands": []}
            cells.append(attach)
        attach["srcs"].add(u["src"])
        for cd in attach["cands"]:
            if sim((cd["key"], cd["kind"]), (u["key"], u["kind"])) >= 0.8:
                cd["reads"][u["src"]] = (u["s"], u["e"])
                break
        else:
            attach["cands"].append({"key": u["key"], "kind": u["kind"], "reads": {u["src"]: (u["s"], u["e"])},
                                    "surf": u["surf"], "wid": u["wid"]})
        attach["s"] = float(np.median([s for cd in attach["cands"] for s, _ in cd["reads"].values()]))
        attach["e"] = float(np.median([e for cd in attach["cands"] for _, e in cd["reads"].values()]))
    cells.sort(key=lambda c: c["s"])
    return cells


# ---------------------------------------------------------------- 第 1 步：整首顺序对齐

def gains(cells, ly):
    """[网格单元 × Genius 单元] 的得分（相似度 − TAU，候选里取最高；多遍支持的稍加分），以及取到最高的是哪个候选。"""
    U, T = len(cells), ly.T
    G = np.full((U, T), -1.0, dtype=np.float32)
    W = np.zeros((U, T), dtype=np.int16)
    gk = {}
    for t, tk in enumerate(ly.tok):
        gk.setdefault((tk[0], tk[1]), []).append(t)
    from rapidfuzz import fuzz, process
    wkeys = [k for k in gk if k[1] == "w"]
    wstr = [k[0] for k in wkeys]
    def gain(sc, n_reads, t):
        """相似度 → 得分：只有一遍听到的减半（幻听、复读多半只出现在一遍里）；
        括号里的和声、语气词对上了不加分（只比算歌词外略好，不值得为它跳转）。"""
        v = sc - TAU
        if v > 0:
            v *= 1.0 if n_reads >= 2 else 0.5
            v += 0.05 * (n_reads - 1)
        if ly.opt[t]:
            v = min(v, 0.0) - (INS - 0.05)
        return v
    for u, c in enumerate(cells):
        for ci, cd in enumerate(c["cands"]):
            nr = len(cd["reads"])
            if cd["kind"] == "k":
                for t in gk.get((cd["key"], "k"), []):
                    v = gain(1.0, nr, t)
                    if v > G[u, t]:
                        G[u, t], W[u, t] = v, ci
                continue
            if not wstr:
                continue
            scores = process.cdist([cd["key"]], wstr, scorer=fuzz.ratio)[0] / 100
            for k, sc in zip(wkeys, scores):
                if (len(cd["key"]) <= 2 or len(k[0]) <= 2) and cd["key"] != k[0]:
                    sc = 0.0
                if sc < 0.35:
                    continue
                for t in gk[k]:
                    v = gain(sc, nr, t)
                    if v > G[u, t]:
                        G[u, t], W[u, t] = v, ci
    return G, W


def jump_matrix(n):
    """J[l, L]：从第 l 行行尾跳到第 L 行行首的代价。"""
    l = np.arange(n)[:, None]
    L = np.arange(n)[None, :]
    J = np.where(L == l + 1, 0.0, np.where(L == l, REP, np.where(L < l, BACK, np.minimum(SKIP * (L - l - 1), FAR))))
    return J.astype(np.float32)


def viterbi(cells, ly, G):
    """返回每个网格单元的去向：('m', t, 是否新的一次（进入一行）) 或 ('i', None)。"""
    U, T, nl = len(cells), ly.T, len(ly.lines)
    NEG = -1e9
    J = jump_matrix(nl)
    starts = np.array(ly.start)
    ends = np.array(ly.end)
    # exitc[t]：在第 t 个单元离开这一行，后面没唱的单元的代价（封顶 EXIT）
    exitc = np.zeros(T, np.float32)
    for k in range(nl):
        acc = 0.0
        for t in range(ends[k] - 1, starts[k] - 1, -1):
            exitc[t] = min(EXIT, acc)
            acc += ly.skipc[t]
    same_line = np.array(ly.line_of)
    score = np.full(T, NEG, np.float32)
    pre = 0.0
    bp_kind = np.zeros((U, T), np.int8)     # 0 插入（停在 t）；1~4 同行前进 d；5 进入一行（从别的行 / 开头）
    bp_from = np.full((U, T), -1, np.int32)  # 进入一行时从哪个单元来（-2 = 开头）
    pre_hist = np.zeros(U, np.float32)
    for u in range(U):
        prev = score
        cand = np.full(T, NEG, np.float32)
        kind = np.zeros(T, np.int8)
        frm = np.full(T, -1, np.int32)
        # 同一行前进 d 个单元（中间跳过的扣 DEL）
        for d in range(1, 5):
            sh = np.full(T, NEG, np.float32)
            sh[d:] = prev[:-d]
            cost = np.zeros(T, np.float32)
            for x in range(1, d):
                c2 = np.zeros(T, np.float32)
                c2[d:] = ly.skipc[d - x:T - x]
                cost += c2
            ok = np.zeros(T, bool)
            ok[d:] = same_line[d:] == same_line[:-d]
            v = np.where(ok, sh - cost, NEG)
            better = v > cand
            cand = np.where(better, v, cand)
            kind = np.where(better, d, kind)
        # 进入一行：从任意一行的任意位置离开（扣没唱完的）+ 行间跳转；或者从开头进入
        leave = prev - exitc
        lex = np.maximum.reduceat(leave, starts)
        larg = np.array([starts[k] + int(np.argmax(leave[starts[k]:ends[k]])) for k in range(nl)])
        via = lex[:, None] - J                 # [从哪行, 到哪行]
        best_l = np.argmax(via, axis=0)
        entry = via[best_l, np.arange(nl)]
        # 从歌词开始前进入某一行：越靠后的行代价越高一点（同样像的时候选前面的段落：Dai Dai 开头和结尾的歌词几乎一样，
        # 开头被对到了结尾那段）
        from_pre = pre - START - START_STEP * np.arange(nl)
        use_pre = from_pre > entry
        entry = np.where(use_pre, from_pre, entry)
        src = np.where(use_pre, -2, larg[best_l])
        # 进入时可以跳过行首几个单元（扣 DEL）
        for k in range(nl):
            acc = 0.0
            for t in range(starts[k], min(ends[k], starts[k] + 4)):
                v = entry[k] - acc
                if v > cand[t]:
                    cand[t], kind[t], frm[t] = v, 5, src[k]
                acc += ly.skipc[t]
        matched = cand + G[u]
        stay = prev - INS
        take = matched >= stay
        score = np.where(take, matched, stay).astype(np.float32)
        bp_kind[u] = np.where(take, kind, 0)
        bp_from[u] = np.where(take & (kind == 5), frm, -1)
        pre_hist[u] = pre
        pre = pre - INS
    # 回溯
    path = [("i", None, False)] * U
    t = int(np.argmax(score))
    if pre >= score[t]:
        return path
    u = U - 1
    while u >= 0 and t >= 0:
        k = bp_kind[u, t]
        if k == 0:
            path[u] = ("i", None, False)
            u -= 1
            continue
        if k == 5:
            path[u] = ("m", t, True)
            t = int(bp_from[u, t])
            u -= 1
            if t == -2:
                break
            continue
        path[u] = ("m", t, False)
        t -= int(k)
        u -= 1
    return path


# ---------------------------------------------------------------- 唱到的每一行（一次）

def occurrences(cells, ly, path, W):
    """把对齐路径切成「每次唱到的 Genius 行」：从进入一行开始，到下一次进入为止。"""
    occ, cur = [], None
    for u, (kind, t, new) in enumerate(path):
        if kind != "m":
            continue
        k = ly.line_of[t]
        if new or cur is None or cur["k"] != k:
            cur = {"k": k, "cells": [], "toks": [], "entered": new}
            occ.append(cur)
        cur["cells"].append(u)
        cur["toks"].append(t)
    # 一次唱到的行里，中间停顿 > STRAY_GAP、那一截只有一个单元：不算这一行的（零星听到的词被接到行尾，把行拉长）
    trimmed = []
    for o in occ:
        parts, cur = [], [0]
        for i in range(1, len(o["cells"])):
            if cells[o["cells"][i]]["s"] - cells[o["cells"][i - 1]]["e"] > STRAY_GAP:
                parts.append(cur)
                cur = []
            cur.append(i)
        parts.append(cur)
        keep = [p for p in parts if len(p) >= 2] or [max(parts, key=len)]
        for p in keep:
            trimmed.append({**o, "cells": [o["cells"][i] for i in p], "toks": [o["toks"][i] for i in p],
                            "entered": o["entered"] if p is keep[0] else False})
    occ = trimmed
    for o in occ:
        k = o["k"]
        req = [t for t in range(ly.start[k], ly.end[k]) if not ly.opt[t]] or list(range(ly.start[k], ly.end[k]))
        got = set(o["toks"])
        o["coverage"] = len(got & set(req)) / len(req)
        sims, sup, cds = [], [], []
        for u, t in zip(o["cells"], o["toks"]):
            cd = cells[u]["cands"][int(W[u, t])]
            sims.append(sim((cd["key"], cd["kind"]), ly.tok[t][:2]))
            sup.append(len(cd["reads"]))
            cds.append(cd)
        o["sim"] = float(np.mean(sims))
        o["support"] = float(np.mean(sup))
        # 现场改词：多遍都听到（≥ 2 遍）、5 个字母以上的实词里，和对上的 Genius 词明显不一样（< 0.75）的占一半以上
        # （GIRL LIKE ME 报国家名「las argentinas」被对到「La-la-latinas」；BZRP 观众合唱「Ella arrastraba la vecina
        #  a la suegra」里 vecina / suegra 都对得上，不算改词）
        mism = tot = 0
        seen = set()
        for cd, sm in zip(cds, sims):
            if cd["kind"] != "w" or len(cd["key"]) < 5 or len(cd["reads"]) < 2 or cd["wid"] in seen:
                continue
            seen.add(cd["wid"])
            tot += len(cd["key"])
            mism += len(cd["key"]) if sm < 0.75 else 0
        # 还要 Genius 这一行对上的不到一半：对上一半以上（una loba / como / tipos / como tú）就是这句歌词，只是有个词听错了
        # （BZRP 2:11「como yo no está pa'」听成「como lobita」）
        # 只数读音真的像（≥ 0.75）的词：「las argentinas」里 las≈la、argentinas≈latinas 都只是勉强像，不算对上
        good = {t for t, sm in zip(o["toks"], sims) if sm >= 0.75 and t in set(req)}
        o["live_change"] = tot > 0 and mism / tot > 0.5 and len(good) < 0.5 * max(1, len(req))
        o["cands"] = cds
        o["s"] = cells[o["cells"][0]]["s"]
        o["e"] = cells[o["cells"][-1]]["e"]
    # 顺序连贯：上一次唱到的是上一行（或本行重复、或开头）
    for i, o in enumerate(occ):
        p = occ[i - 1]["k"] if i else None
        o["natural"] = p is None or o["k"] == p + 1 or o["k"] == p
    return occ


def confidence(o, ly, n_reads):
    """一个公式：文字 × 遍数 × 顺序 × 独特。"""
    text = o["coverage"] * o["sim"]
    reads = min(1.0, o["support"] / max(1.0, min(2.0, n_reads)))
    order = 1.0 if o["natural"] else 0.8
    uniq = 1.0 if ly.dups[o["k"]] == 1 else 0.85
    return text * reads * order * uniq


def heard_text(o, cells):
    """这一次唱到的行，识别听到的原文（按时间、去掉同一个词拆出来的重复）。"""
    out, last = [], None
    for cd in o["cands"]:
        if cd["wid"] != last:
            out.append(cd["surf"])
            last = cd["wid"]
    txt = ""
    for w in out:
        txt += ("" if txt and CJK.search(txt[-1:]) and CJK.search(w[:1]) else " ") + w
    return txt.strip()


def run_alignment(reads, ly):
    cells = lattice(reads)
    if not cells or not ly.T:
        return cells, [], []
    G, W = gains(cells, ly)
    path = viterbi(cells, ly, G)
    occ = occurrences(cells, ly, path, W)
    n = len({u["src"] for ws in reads for u in ws})
    for o in occ:
        o["conf"] = confidence(o, ly, n)
        o["anchor"] = o["conf"] >= ANCHOR and o["coverage"] >= 0.5
        o["heard"] = heard_text(o, cells)
    return cells, path, occ
