# -*- coding: utf-8 -*-
"""
全局对齐（替代 concert_align + gap_fill 的十几步修补，原因见 docs/design/v2_alignment_root_causes.md）。

  1. 整首连续转写：人声按固定的 6 s 一块、每 3 s 一块（重叠 3 s）送 Qwen，每块只取中间 3 s 的词；
     识别文字用 MMS 在人声上逐词强制对齐，得到每个词的时间。切法固定、不依赖任何上游结果，所以结果稳定。
  2. 歌词 ↔ 转写做一次全局序列对齐（词级，读音键相似：zangalewa ≈ sangaleva）：
     顺着歌词往下唱不罚分，跳句 / 回到前面重唱 / 现场插进来的词各有罚分；括号里的和声词可以不唱。
       - 对上的歌词句：用 Genius 原句
       - 转写里连续一段没对上歌词：现场改词 / 即兴 / 喊话，按停顿切成短句，用 Qwen 的文字；
         要 2.5 s 窗口识别（另一种切法）也听到同样的词才保留，挡人群声里的幻听
       - 歌词里没对上的句子：没唱，不出字幕
  3. 声学定时（v1 refine_timing 的做法）：每句 Genius 原句在「前后句之间」用 MMS 强制对齐，取首词起点 / 末词终点；
     MMS 对齐分低的句子标「声学不像」
  4. 每句统一提前 LEAD 秒出现，不压上一句
逐句 Qwen 复核（verify_qwen）在这之后只做检查、标红，不改字幕。
"""

import json
import os
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


def vocab_score(text, vocab):
    """识别文字里有多少比例的词（3 个字母以上）是这首歌词里的词（读音键近似）。"""
    from rapidfuzz import fuzz, process
    from .gap_fill import phon
    toks = [phon(w) for w in _tok(text) if len(w) >= 3]
    if not toks:
        return 0.0
    return sum(1 for t in toks if process.extractOne(t, vocab, scorer=fuzz.ratio, score_cutoff=80)) / len(toks)


def transcribe_song(y, sr, lang, client, mms, em, fr, vocab=(), langs=("auto",)):
    from qwen_asr import transcribe
    from refine_timing import romanize
    from .gap_fill import NON_LATIN
    _, tokenizer, aligner = mms
    dur = len(y) / sr
    from concurrent.futures import ThreadPoolExecutor
    words = []
    starts = list(np.arange(0.0, max(dur - 1.0, 0.01), CHUNK_HOP))
    jobs = [(c0, lg) for c0 in starts for lg in langs]

    def read(job):
        c0, lg = job
        return job, transcribe(client, y[int(c0 * sr):int(min(dur, c0 + CHUNK) * sr)], lg) or ""
    with ThreadPoolExecutor(3) as ex:   # 3 路并发，和 v1 qwen_dense 一样，不会触发限流
        got = dict(ex.map(read, jobs))
    for c0 in starts:
        c1 = min(dur, c0 + CHUNK)
        # 同一块按几种语种各听一遍（auto 在 6 s 的嘈杂片段上常认错语种：Dai Dai 3:10 被认成法语 / 意大利语），
        # 选和这首歌词词汇最对得上的；都对不上（现场喊话）就用 auto
        reads = [(lg, got[(c0, lg)]) for lg in langs]
        scored = [(vocab_score(t, vocab) if vocab else 0.0, -i, t) for i, (lg, t) in enumerate(reads)]
        text = max(scored)[2] if max(scored)[0] > 0 else reads[0][1]
        raw = [w for w in _tok(text) if not NON_LATIN.search(w) or lang in ("zh", "ja", "ko", "ru")]
        # 连成一串的语气词（Ohayohayehayohayehay）拆成一个个
        raw = [x for w in raw for x in (INTERJ_SYL.findall(w) if len(w) >= 6 and INTERJ_BLOB.match(w) else [w])]
        toks, own = [], []
        for i, w in enumerate(raw):
            for r in romanize(w, lang):
                toks.append(r)
                own.append(i)
        if not toks:
            continue
        a0, a1 = int(c0 * fr), int(c1 * fr)
        try:
            spans = aligner(em[a0:a1], tokenizer(["*"] + toks + ["*"]))[1:-1]
        except Exception:  # noqa: BLE001
            continue
        per = {}
        for sp, i in zip(spans, own):
            if not sp:
                continue
            t0, t1 = c0 + sp[0].start / fr, c0 + sp[-1].end / fr
            sc = float(np.mean([x.score for x in sp]))
            if i in per:
                per[i] = (min(per[i][0], t0), max(per[i][1], t1), (per[i][2] + sc) / 2)
            else:
                per[i] = (t0, t1, sc)
        ov = (CHUNK - CHUNK_HOP) / 2
        lo = c0 + ov if c0 > 0 else 0.0
        hi = c1 - ov if c1 < dur - 0.01 else dur + 1
        for i, (t0, t1, sc) in sorted(per.items()):
            if lo <= (t0 + t1) / 2 < hi:
                words.append({"w": raw[i], "s": t0, "e": t1, "score": sc})
    words.sort(key=lambda x: x["s"])
    return words


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


def window_words(words, windows, min_gap=2.0):
    """整首转写里空着的地方（≥ min_gap 秒没有词），用 2.5 s 窗口的识别补词：至少两个窗口都听到的词才算，
    时间取听到它的那几个窗口的中间（Waka Waka 0:17~0:29 整首转写几乎没词，窗口听到了 Sangaleva / Otra, otra）。"""
    from .gap_fill import phon
    times = [0.0] + [w["s"] for w in words] + [1e9]
    gaps = [(a, b) for a, b in zip(times, times[1:]) if b - a >= min_gap]
    out = []
    for g0, g1 in gaps:
        ws = [(t, _tok(v or "")) for t, v in windows if g0 - 1.0 <= t <= g1 - 1.5]
        seen = {}
        for t, toks in ws:
            for k, w in enumerate(toks):
                key = phon(w)
                if len(key) < 2:
                    continue
                seen.setdefault(key, []).append((t, w, toks.count(w)))
        for key, hits in seen.items():
            if len({t for t, _, _ in hits}) < 2:
                continue
            # 按时间分簇（相邻窗口都听到的是同一次），每簇按单个窗口里最多出现几次算几个词
            hits.sort()
            cl = [[hits[0]]]
            for h in hits[1:]:
                (cl[-1].append(h) if h[0] - cl[-1][-1][0] <= 1.0 else cl.append([h]))
            for c in cl:
                if len({t for t, _, _ in c}) < 2:
                    continue
                n = max(m for _, _, m in c)
                t0, t1 = c[0][0] + 1.25, c[-1][0] + 1.25
                for i in range(n):
                    tm = t0 + (t1 - t0) * (i + 0.5) / n
                    out.append({"w": c[0][1], "s": tm - 0.2, "e": tm + 0.2, "score": 0.0, "src": "window"})
    return sorted(words + [w for w in out if not any(abs(w["s"] - x["s"]) < 0.3 for x in words)], key=lambda x: x["s"])


def window_text(windows, s, e):
    return " ".join(v or "" for t, v in windows if t + 2.5 > s + 0.3 and t < e - 0.3)


def phrase_score(heard_texts, line):
    """几段听到的文字里，和这句歌词整句读音最像的分数（0~100）。"""
    from rapidfuzz import fuzz
    from .gap_fill import phon
    ref = " ".join(phon(w) for w, _ in lyric_tokens([line])[0])
    best = 0.0
    for h in heard_texts:
        hp = " ".join(phon(w) for w in _tok(h))
        if not hp:
            continue
        sc = fuzz.ratio(hp, ref)
        if len(hp) >= len(ref):   # 窗口文字比这句长：看这句是不是整句出现在里面
            sc = max(sc, fuzz.partial_ratio(ref, hp) - 5)
        best = max(best, sc)
    return best


def fill_from_windows(items, lines, windows, dur):
    """没字幕的空档里，2.5 s 窗口听到了按歌词顺序该唱的那句（整句读音像），就补上这句
    （GIRL LIKE ME 1:23 整首转写听成 shout shout / shock it up，窗口听到 Shakira, Shak, Shak, Shakira）。"""
    items = sorted(items, key=lambda x: x["s"])
    bounds = [(0.0, 0.0)] + [(it["s"], it["e"]) for it in items] + [(dur, dur)]
    added = []
    for (_, g0), (g1, _) in zip(bounds, bounds[1:]):
        if g1 - g0 < 1.5:
            continue
        ws = [(t, v) for t, v in windows if t >= g0 - 0.5 and t + 2.5 <= g1 + 0.5 and v]
        if not ws:
            continue
        for k in _expected(items + added, lines, g0, g1):
            hits = [t for t, v in ws if phrase_score([v], lines[k]) >= 70]
            if len(hits) >= 2:   # 至少两个窗口都听到
                s0, e0 = max(g0 + 0.05, min(hits) + 0.5), min(g1 - 0.05, max(hits) + 2.0)
                if e0 - s0 >= 0.5:
                    added.append({**_lyric_item(k, lines, s0, e0, 0.0, "空档里 2.5 s 窗口听到了按顺序该唱的这句"), "ev": None})
    return items + added


def snap_phrases(items, lines, windows=()):
    """现场插入的短句整句读音像「按歌词顺序该在这里」的那句（Pensó recogió su avión ≈ Perdón, ya cogí otro avión），
    就当成这句歌词。"""
    from rapidfuzz import fuzz
    from .gap_fill import phon
    out = list(items)
    for i, it in enumerate(out):
        if it["kind"] != "qwen":
            continue
        texts = [it["text"], window_text(windows, it["s"], it["e"])]
        best = None
        for k in _expected(out, lines, it["s"], it["e"]):
            sc = phrase_score(texts, lines[k])
            if sc >= 65 and (best is None or sc > best[0]):
                best = (sc, k)
        if best:
            sc, k = best
            need = [w for w, opt in lyric_tokens([lines[k]])[0] if not opt and w.lower() not in INTERJ]
            out[i] = {**it, "kind": "lyric", "line": k, "text": _clean(lines[k]), "genius": lines[k], "cover": 0.0,
                      "got": 0, "need": len(need), "how": f"Qwen 听到「{it['text']}」，整句读音像按顺序该唱的这句（{sc:.0f} 分）"}
    return out


def phrases_of(item):
    """现场插入的一段按停顿切成短句。"""
    out, cur = [], []
    for w in item["words"]:
        if cur and (w["s"] - cur[-1]["e"] > PHRASE_GAP or len(cur) >= MAX_PHRASE):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def confirmed(ph, windows):
    """另一种切法（2.5 s 窗口识别）也听到了这段里一半以上的实词，才不是幻听。"""
    from .gap_fill import _phon_close
    s, e = ph[0]["s"], ph[-1]["e"]
    heard = [x for t, v in windows if t + 2.5 > s and t < e for x in _tok(v or "")]
    need = [w["w"] for w in ph if w["w"].lower() not in INTERJ and len(w["w"]) >= 2]
    if not need:
        return False
    hit = sum(1 for w in need if any(_phon_close(w, h) or w.lower() == h.lower() for h in heard))
    return hit / len(need) >= 0.5


# ---------------------------------------------------------------- 3. 声学定时

def time_line(text, lo, hi, lang, mms, em, fr):
    """在 [lo, hi] 里把这句强制对齐到人声：返回 (起, 止, 平均分)；对不上返回 None。"""
    from refine_timing import romanize
    _, tokenizer, aligner = mms
    toks = romanize(text, lang)
    if not toks or hi - lo < 0.3:
        return None
    a0, a1 = int(lo * fr), int(hi * fr)
    try:
        spans = aligner(em[a0:a1], tokenizer(["*"] + toks + ["*"]))[1:-1]
    except Exception:  # noqa: BLE001
        return None
    spans = [sp for sp in spans if sp]
    if not spans:
        return None
    s = lo + spans[0][0].start / fr
    e = lo + spans[-1][-1].end / fr
    sc = float(np.mean([x.score for sp in spans for x in sp]))
    return s, e, sc


class Acoustic:
    """v1 acoustic.py 的声学证据：(NLL(只有 *) - NLL(* 这句 *)) / 字母数，越大越像在唱这句。不依赖 Qwen 的文字。"""

    def __init__(self, em, fr, mms, lang):
        import torch.nn.functional as F
        self.lp, self.fr, self.lang = F.log_softmax(em, dim=-1), fr, lang
        self.tokenizer = mms[1]
        from torchaudio.pipelines import MMS_FA
        self.star = MMS_FA.get_dict(star="*")["*"]
        self.cache = {}

    def tokens(self, text):
        from refine_timing import romanize
        words = romanize(text, self.lang)
        return [t for w in self.tokenizer(words) for t in w] if words else []

    def evidence(self, text, t0, t1):
        import torch
        import torch.nn.functional as F
        key = (text, round(t0, 2), round(t1, 2))
        if key in self.cache:
            return self.cache[key]
        toks = self.tokens(text)
        a, b = max(0, int(t0 * self.fr)), min(self.lp.shape[0], int(t1 * self.fr))
        if not toks or b - a < len(toks) + 2:
            self.cache[key] = -9.0
            return -9.0
        lp = self.lp[a:b].unsqueeze(1)
        T = torch.tensor([b - a])

        def nll(tg):
            return F.ctc_loss(lp, torch.tensor([tg]), T, torch.tensor([len(tg)]), blank=0,
                              reduction="sum", zero_infinity=True).item()
        ev = (nll([self.star]) - nll([self.star] + toks + [self.star])) / len(toks)
        self.cache[key] = ev
        return ev

    def best_in(self, text, lo, hi, dur):
        """在 [lo, hi] 里找这句最像的位置（开头每 0.25 s 试一次，时长按字数估、放宽 0.7~1.4 倍）。"""
        best = (-9.0, lo, lo + dur)
        for s0 in np.arange(lo, max(lo, hi - 0.5 * dur) + 1e-6, 0.25):
            for k in (0.7, 1.0, 1.4):
                e0 = min(hi, s0 + dur * k)
                if e0 - s0 < 0.4:
                    continue
                ev = self.evidence(text, float(s0), float(e0))
                if ev > best[0]:
                    best = (ev, float(s0), float(e0))
        return best


def _time_all(items, lang, mms, em, fr, dur):
    """Genius 句在前后句之间用 MMS 强制对齐，取首词起点 / 末词终点（v1 refine_timing 的声学定时，但有前后句夹着）。"""
    items.sort(key=lambda x: x["s"])
    for i, it in enumerate(items):
        if it["kind"] != "lyric":
            it.setdefault("acoustic", None)
            continue
        lo = max(items[i - 1]["e"] if i else 0.0, it["s"] - 1.5)
        hi = min(items[i + 1]["s"] if i + 1 < len(items) else dur, it["e"] + 1.0)
        r = time_line(it["text"], lo, hi, lang, mms, em, fr)
        if r and r[0] < it["e"] + 0.5 and r[1] > it["s"] - 0.5:
            it["s"], it["e"], it["acoustic"] = r[0], max(r[1], r[0] + 0.3), round(r[2], 3)
        else:
            it.setdefault("acoustic", None)


def _char_rate(items, ac):
    """本歌唱一个字母大约多少秒（估空档里候选句的时长用）。"""
    r = [(it["e"] - it["s"]) / max(1, len(ac.tokens(it["text"]))) for it in items if it["kind"] == "lyric" and it["e"] > it["s"]]
    return float(np.median(r)) if r else 0.08


def _expected(items, lines, lo, hi, limit=8):
    """[lo, hi] 前后最近的两句歌词，在歌词里夹在中间的句子（按顺序）；前面没有就从头，后面没有就往后 limit 句。"""
    prev = max((it for it in items if it["kind"] == "lyric" and it["e"] <= lo + 0.3), key=lambda x: x["e"], default=None)
    nxt = min((it for it in items if it["kind"] == "lyric" and it["s"] >= hi - 0.3), key=lambda x: x["s"], default=None)
    p = prev["line"] if prev else -1
    n = nxt["line"] if nxt else min(len(lines), p + 1 + limit)
    if n <= p + 1:
        n = min(len(lines), p + 1 + limit // 2)   # 后一句在歌词里更靠前（重唱 / 换序）：顺着前一句往下找
    cand = list(range(p + 1, n))[-limit:] if p < 0 else list(range(p + 1, n))[:limit]
    near = {it["text"] for it in items if abs(it["s"] - lo) < 8 or abs(it["s"] - hi) < 8}
    return [k for k in cand if lyric_tokens([lines[k]])[0] and _clean(lines[k]) not in near]


def _clean(line):
    from .gap_fill import clean_parens
    return clean_parens(line)


def _lyric_item(k, lines, s, e, ev, how):
    need = [w for w, opt in lyric_tokens([lines[k]])[0] if not opt and w.lower() not in INTERJ]
    return {"kind": "lyric", "line": k, "s": s, "e": e, "text": _clean(lines[k]), "genius": lines[k], "words": [],
            "cover": 0.0, "got": 0, "need": len(need), "ev": round(ev, 3), "how": how}


def _snap_inserts(items, lines, ac, min_ev, rate):
    """现场插入的短句，读音像按顺序该唱、却没对上的那句歌词（Shaka shaka ≈ Sha-Sha-Shakira），声学上也像，就换成这句歌词。"""
    from .gap_fill import _phon_close
    out = list(items)
    for i, it in enumerate(out):
        if it["kind"] != "qwen":
            continue
        heard = [w["w"] for w in it["words"]]
        best = None
        for k in _expected(out, lines, it["s"], it["e"]):
            toks = [w for w, opt in lyric_tokens([lines[k]])[0] if not opt]
            hit = sum(1 for w in toks if any(_phon_close(w, h) for h in heard))
            if hit < 1 or hit / len(toks) < 0.4:
                continue
            dur = max(it["e"] - it["s"], len(ac.tokens(lines[k])) * rate)
            ev, s0, e0 = ac.best_in(_clean(lines[k]), max(0.0, it["s"] - 0.5), it["e"] + 0.5, dur)
            if ev >= min_ev and (best is None or ev > best[0]):
                best = (ev, k, s0, e0)
        if best:
            ev, k, s0, e0 = best
            out[i] = _lyric_item(k, lines, s0, e0, ev, "现场插入的词读音像这句歌词，声学也像，换成 Genius 原句")
    return out


def _fill_gaps(items, lines, ac, min_ev, rate, dur):
    """空档里补「按歌词顺序该唱、但转写没对上」的句子：每句在空档里用声学找最像的位置，够像才补
    （Dale、Oh-eh-oh-eh、Uh, zangalewa 这种 Qwen 认不准的句子，声学上照样听得出来）。"""
    items = sorted(items, key=lambda x: x["s"])
    bounds = [(0.0, 0.0)] + [(it["s"], it["e"]) for it in items] + [(dur, dur)]
    added = []
    for (_, g0), (g1, _) in zip(bounds, bounds[1:]):
        if g1 - g0 < GAP_MIN:
            continue
        t = g0 + 0.05
        for k in _expected(items + added, lines, g0, g1):
            d = max(0.6, len(ac.tokens(lines[k])) * rate)
            if g1 - t < 0.6 * d:
                break
            ev, s0, e0 = ac.best_in(_clean(lines[k]), t, g1 - 0.05, d)
            need = min_ev + (0.5 if is_pure(lines[k]) else 0.0)   # 语气词句容易蒙上，门槛高一点
            if ev >= need:
                added.append(_lyric_item(k, lines, s0, e0, ev, "空档里按歌词顺序该唱，声学找到"))
                t = e0 + 0.05
    return items + added


def is_pure(line):
    toks = [w for w, opt in lyric_tokens([line])[0] if not opt]
    return bool(toks) and all(w.lower() in INTERJ for w in toks)


def keep_adjacent(items, lines):
    """纯语气词句只留紧挨着真歌词的（链式）：开场、间奏里人群喊的 hey / uh huh 会被配成「Ayy, yeah」。"""
    pure = [it["kind"] == "lyric" and is_pure(lines[it["line"]]) for it in items]
    ok = [not p for p in pure]
    changed = True
    while changed:
        changed = False
        for i, it in enumerate(items):
            if ok[i]:
                continue
            for j in (i - 1, i + 1):
                if 0 <= j < len(items) and ok[j] and items[j]["kind"] == "lyric":
                    gap = it["s"] - items[j]["e"] if j < i else items[j]["s"] - it["e"]
                    if gap <= ADJACENT:
                        ok[i] = changed = True
                        break
    return [it for it, k in zip(items, ok) if k]


# ---------------------------------------------------------------- 主流程

def align(song_dir, lang, out_srt, lyrics):
    import librosa
    import llm
    import pysubs2
    from openai import OpenAI
    from qwen_asr import ENDPOINT, SR
    from refine_timing import emission_full, load_model
    from .gap_fill import clean_parens, voiced_ratio

    d = song_dir
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(str(d / "vocals.wav"), sr=SR, mono=True)
    mms = load_model()
    em, fr = emission_full(mms[0], y)
    lines = [l.strip() for l in lyrics if l.strip()]
    from .gap_fill import phon
    vocab = sorted({phon(w) for l in lines for w in _tok(l) if len(w) >= 3})
    langs = list(dict.fromkeys(["auto", lang if lang != "auto" else "es", "es", "en"]))
    words = transcribe_song(y, SR, lang, client, mms, em, fr, vocab, langs)
    cache_f = d / "reports" / "dense_cache.json"
    windows = sorted((float(k), v) for k, v in json.loads(cache_f.read_text()).items()) if cache_f.exists() else []
    words = window_words(words, windows)
    path = decode(words, lines)
    items = occurrences(words, path, lines)

    # 现场插入的段：按停顿切句，另一种切法也听到 + 有人声才保留
    subs_items = []
    for it in items:
        if it["kind"] == "lyric":
            subs_items.append({**it, "text": clean_parens(lines[it["line"]]), "genius": lines[it["line"]]})
            continue
        for ph in phrases_of(it):
            text = " ".join(w["w"] for w in ph)
            content = [w for w in ph if w["w"].lower() not in INTERJ]
            if not content or not confirmed(ph, windows) or voiced_ratio(y, SR, ph[0]["s"], ph[-1]["e"] + 0.01) < 0.3:
                continue
            subs_items.append({"kind": "qwen", "s": ph[0]["s"], "e": ph[-1]["e"], "words": ph,
                               "text": text[0].upper() + text[1:], "genius": ""})
    subs_items.sort(key=lambda x: x["s"])
    subs_items = snap_phrases(subs_items, lines, windows)
    subs_items = fill_from_windows(subs_items, lines, windows, len(y) / SR)
    subs_items = keep_adjacent(sorted(subs_items, key=lambda x: x["s"]), lines)
    ac = Acoustic(em, fr, mms, lang)
    _time_all(subs_items, lang, mms, em, fr, len(y) / SR)
    # 声学证据（v1 acoustic）只记下来，不用来取舍：在这场演唱会的人声上它分不清是哪句
    # （唱对的句子和配错的句子分数差不多，见 docs/design/v2_alignment_root_causes.md），只有定时靠 MMS
    for it in subs_items:
        if it["kind"] == "lyric":
            it["ev"] = round(ac.evidence(it["text"], it["s"], it["e"]), 3)

    # 显示时间：句末多留一会儿、最短显示时间、不重叠、统一提前
    for i, it in enumerate(subs_items):
        nxt = subs_items[i + 1]["s"] if i + 1 < len(subs_items) else it["e"] + 5
        it["show_e"] = min(max(it["e"] + HOLD, it["s"] + MIN_SHOW), nxt - 0.05)
    prev_e = 0.0
    for it in subs_items:
        it["show_s"] = max(prev_e + 0.05, it["s"] - LEAD, 0.0)
        it["show_e"] = max(it["show_e"], it["show_s"] + 0.3)
        prev_e = it["show_e"]

    subs = pysubs2.SSAFile()
    for it in subs_items:
        subs.events.append(pysubs2.SSAEvent(start=int(it["show_s"] * 1000), end=int(it["show_e"] * 1000), text=it["text"]))
    subs.save(str(out_srt))
    rep = d / "reports"
    (rep / "transcript.json").write_text(json.dumps(words, ensure_ascii=False, indent=0))
    (rep / "align2.json").write_text(json.dumps([{k: v for k, v in it.items() if k != "words"} | {
        "heard_words": " ".join(w["w"] for w in it.get("words", []))} for it in subs_items], ensure_ascii=False, indent=1))
    return subs_items


def strategy_of(it):
    if it.get("how"):
        return it["how"]
    if it["kind"] == "lyric":
        s = f"全局对齐：Genius 原句（Qwen 整首转写对上 {it['got']}/{it['need']} 个实词）+ MMS 声学定时" if it["need"] \
            else "全局对齐：Genius 原句（语气词句）+ MMS 声学定时"
        return s
    return "全局对齐：Genius 里没有（现场改词 / 即兴），用 Qwen 转写；2.5 s 窗口也听到"


def write_lines(song_dir, items, verify):
    """审核页逐句表格（reports/lines.json）：Genius 原句 / Qwen 复核听到 / 校准字幕 / 校准策略。"""
    vl = verify.get("lines", [])
    sus = {round(x["start"], 1): x["score"] for x in verify.get("suspect", [])}
    out = []
    for it in items:
        m = min(vl, key=lambda v: abs(v["start"] - it["show_s"]), default=None)
        heard = (m.get("heard") or "") if m and abs(m["start"] - it["show_s"]) < 0.3 else ""
        score = next((v for k, v in sus.items() if abs(k - it["show_s"]) < 0.3), None)
        out.append({"start_ms": round(it["show_s"] * 1000), "end_ms": round(it["show_e"] * 1000), "genius": it["genius"],
                    "heard": heard, "text": it["text"], "strategy": strategy_of(it), "removed": False,
                    "suspect": score})   # 只看逐句 Qwen 复核；声学分在这场演唱会上不可靠，不标
    (song_dir / "reports" / "lines.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out
