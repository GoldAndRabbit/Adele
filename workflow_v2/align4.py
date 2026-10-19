# -*- coding: utf-8 -*-
"""
v2 实验（方案见 docs/design/v2_alignment_plan.md 第二版）：结果写到 exp_v2/，v1 实验（exp/，align3.py）和 v0 原流程都不动。

比 v1 多的：
  1. 语言档案：整首 + 逐句是什么语言；读音比对、长度、语气词、「像不像词」、拖腔补多少、MMS 用不用都按语言选
     （识别接口的语种参数实测无效：传不传、传错结果都一样，所以只能事后按语言选做法）
  2. 时间投票：每行在三遍识别里各找一次位置（A1 / A2 / A3），加上窗口文本（B）和 MMS（C，只有拉丁字母的句子），
     相差 ≤ 0.5 s 的算一伙，取人数最多的一伙
  3. 查漏：时间不一致的不再列成「漏」；两遍在同一位置都听到的句子补进字幕（标「补」）
  4. 讲话：Genius 里没有、语速快（≥ 2.2 词 / 秒）或在歌词开始前 / 结束后的长段落，归成讲话（黄色字幕，不加 ♪）
"""

import json
import os
import re
from collections import Counter
from functools import lru_cache

import numpy as np

from . import align3 as A3

AGREE = 0.5
MATCH = 70
LEAD, HOLD, MIN_SHOW = 0.2, 0.4, 0.8
LATIN = {"en", "es", "it", "pt", "fr"}
KANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯]")
HAN = re.compile(r"[㐀-鿿]")

STOP = {
    "en": {"the", "and", "you", "i", "me", "my", "is", "it", "to", "a", "of", "in", "that", "for", "your", "be", "we", "on", "with", "what", "like", "girl"},
    "es": {"el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "no", "me", "te", "tu", "mi", "es", "por", "con", "lo", "se", "para", "yo", "más"},
    "it": {"il", "la", "le", "di", "che", "e", "è", "un", "una", "non", "mi", "ti", "per", "con", "si", "ma", "sono", "io", "tu", "perché", "sarà", "amo", "più"},
    "pt": {"o", "a", "os", "as", "de", "que", "e", "em", "um", "uma", "não", "me", "te", "você", "eu", "com", "para", "é", "do", "da"},
    "fr": {"le", "la", "les", "de", "que", "et", "en", "un", "une", "ne", "pas", "je", "tu", "il", "est", "pour", "avec", "moi", "toi"},
}
AMBIG = {"yo", "a", "e", "o", "i", "me", "no", "la", "le", "de", "se", "te", "tu", "mi", "un", "en", "il", "è", "do", "ai"}
STOP["es"] |= {"gracias", "quiero", "mucho", "muchas", "muchísimas", "hola", "bueno", "noche", "todos", "esta", "aquí"}
STOP["it"] |= {"grazie", "bravi", "tutti", "sempre", "ancora", "questo", "anche", "noi"}
INTERJ = {
    "en": {"oh", "ah", "eh", "uh", "yeah", "hey", "ooh", "woo", "whoa", "mm", "hmm", "ha", "huh", "na", "la", "ayy", "ay"},
    "es": {"oh", "ah", "eh", "uh", "ay", "ayy", "aye", "hey", "ole", "oe", "yeah", "mm", "ja", "uh-huh"},
    "it": {"oh", "ah", "eh", "uh", "uè", "mm", "ehi", "yeah"},
    "pt": {"oh", "ah", "eh", "ai", "ui", "yeah"},
    "fr": {"oh", "ah", "eh", "hé", "ouais", "yeah"},
    "ja": {"ah", "aa", "oh", "nee", "ne", "yeah", "hey", "uu", "a"},
}
LETTERS = [("es", r"ñ|ción$|[áíóú]|(?:ana|ena|ina|ano|ola|ado|ada)s?$"), ("pt", r"[ãõç]|ção$|nh|lh"),
           ("it", r"[àèìòù]|zion[ei]$|(?:gli|zz|cch)"), ("fr", r"[âêîôûœ]|eux$|tion$")]
MAX_LINE = {"latin": 8, "cjk": 16}             # 一行最多：拉丁按词、日中韩按字
LEAD_PER = {"latin": 0.35, "ja": 0.2, "zh": 0.25, "ko": 0.25}


# ---------------------------------------------------------------- 1. 语言档案

def line_lang(text, default="en"):
    if KANA.search(text):
        return "ja"
    if HANGUL.search(text):
        return "ko"
    if HAN.search(text):   # 只有汉字（元気？）：日语歌里算日语
        return default if default in ("ja", "zh") else "zh"
    toks = [w.lower() for w in re.findall(r"[^\W\d_]+", text)]
    if not toks:
        return default
    sc = {lg: float(sum(1 for w in toks if w in st)) for lg, st in STOP.items()}
    cue = Counter()
    # 没有虚词的单词句（报国家名：Venezolana, Ecuatoriana）：看字母和词尾
    for w in toks:
        for lg, pat in LETTERS:
            if re.search(pat, w):
                cue[lg] += 1
                sc[lg] += 0.6
                break
    best = max(sc, key=lambda k: (sc[k], k == default))
    if sc[best] <= 0:
        return default
    # 短句只命中几种语言里都常见的短词不算（「Hey yo」的 yo 是西语「我」，但这里是英语喊声）
    strong = [w for w in toks if w in STOP.get(best, ()) and w not in AMBIG]
    if best != default and len(toks) <= 3 and not strong and not cue[best]:
        return default
    return best


def script_of(lang):
    return "cjk" if lang in ("ja", "zh", "ko") else "latin"


def profile(lines, reads, hint=None):
    """整首主语言 / 用到哪些语言 / 每句语言；识别结果的语言和歌词对不上时标出来。"""
    main0 = Counter(line_lang(l) for l in lines).most_common(1)[0][0] if lines else (hint or "en")
    per = [line_lang(l, main0) for l in lines]
    cnt = Counter(per)
    main = cnt.most_common(1)[0][0]
    langs = [lg for lg, n in cnt.most_common() if n >= max(2, 0.1 * len(lines))] or [main]
    heard = Counter(line_lang(A3.text_of(ws[i:i + 20]), main) for ws in reads for i in range(0, len(ws), 20))
    heard_main = heard.most_common(1)[0][0] if heard else main
    return {"main": main, "langs": langs, "script": script_of(main), "per_line": per,
            "heard_main": heard_main, "mismatch": heard_main != main and heard_main not in langs,
            "mms": main in LATIN, "windows": None}


# ---------------------------------------------------------------- 按语言的读音键

def _phon(w, lang):
    import unicodedata
    w = unicodedata.normalize("NFKD", w.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    w = re.sub(r"[^a-z]", "", w)
    if lang == "es":
        w = w.replace("ts", "s").replace("z", "s").replace("w", "b").replace("v", "b").replace("ll", "y").replace("qu", "k").replace("h", "")
        w = re.sub(r"c(?=[ei])", "s", w).replace("c", "k")
    elif lang == "it":
        w = w.replace("gn", "ny").replace("gli", "li").replace("ch", "k").replace("gh", "g").replace("h", "")
        w = re.sub(r"sc(?=[ei])", "sh", w)
        w = re.sub(r"c(?=[ei])", "ch", w).replace("q", "k")
        w = re.sub(r"c(?!h)", "k", w)
    elif lang == "pt":
        w = w.replace("lh", "ly").replace("nh", "ny").replace("ç", "s").replace("qu", "k").replace("h", "")
    elif lang == "en":
        w = w.replace("ph", "f").replace("ck", "k")
        w = re.sub(r"ing$", "in", w)
    elif lang == "ja":
        w = w.replace("ou", "o").replace("uu", "u")
    return re.sub(r"(.)\1+", r"\1", w)


@lru_cache(maxsize=None)
def key(text, lang):
    """读音键（去掉括号里的和声、去掉这门语言的语气词；日文先转罗马音）。"""
    text = re.sub(r"\([^)]*\)", " ", text)
    if lang == "ja" or KANA.search(text) or HAN.search(text):
        text = A3._romaji(text)
    toks = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text)
    ij = INTERJ.get(lang, set())
    keep = [w for w in toks if w.lower() not in ij] or toks
    return " ".join(p for p in (_phon(w, lang) for w in keep) if p)


def score(a, b, lang):
    """按这门语言的读音比，和 v1 的通用读音键（西语式同音：w/v/b、z/s、ll/y，语气词表更宽）比，取高的。
    只用按语言的：Dai Dai「Owe owe」对不上「Oh-eh-oh-eh」、BZRP「Sé pa' que te muerdes」对不上「Esto es pa' que te mortifique'」，
    v1 都对得上；只用 v1 的：意大利语、日语不准。"""
    from rapidfuzz import fuzz
    pa, pb = key(a, lang), key(b, lang)
    mine = float(fuzz.ratio(pa, pb)) if pa and pb and 0.6 <= len(pa) / len(pb) <= 1.7 else 0.0
    return max(mine, A3.score(a, b))


def units(text, lang):
    """长度：拉丁按词，日中韩按字。"""
    if script_of(lang) == "cjk":
        return len(re.sub(r"[\s\W\d_]", "", text))
    return len(re.findall(r"[^\W\d_]+", text))


def word_like(text, lang):
    """「太短、不像词」检查（按语言）。"""
    if lang == "ja":
        return units(text, lang) >= 3
    if lang in ("zh", "ko"):
        return units(text, lang) >= 2
    toks = re.findall(r"[^\W\d_]+", text)
    return sum(1 for w in toks if len(w) >= 3) >= 2 or any(len(w) >= 5 for w in toks)


# ---------------------------------------------------------------- 2. 三遍识别，每 8 s 挑一遍

def pick_reads(reads, lines, prof, bin_s=8.0):
    """每 8 s 从三遍里挑「这一段文字里能找到的 Genius 句子最多」的那遍（按每句的语言比读音）。"""
    from rapidfuzz import fuzz
    keys = [(key(l, lg), len(key(l, lg))) for l, lg in zip(lines, prof["per_line"]) if key(l, lg)]

    def cover(ws):
        if not ws:
            return -1
        t = key(A3.text_of(ws), prof["main"])
        return sum(n for k, n in keys if n >= 4 and fuzz.partial_ratio(k, t) >= 80)
    end = max([w["e"] for ws in reads for w in ws] or [0.0])
    out, t = [], 0.0
    while t < end + bin_s:
        cand = [[w for w in ws if t <= w["s"] < t + bin_s] for ws in reads]
        out += max(enumerate(cand), key=lambda x: (cover(x[1]), len(x[1]), -x[0]))[1]
        t += bin_s
    return sorted(out, key=lambda w: w["s"])


HOLE_MIN = 4.0   # 人声明显、三遍都一个字没有的空洞，至少这么长才单独补识别


def fill_holes(y, sr, key_, cache, reads, lines, lang):
    """三遍整段识别都漏掉的段落：单独截出来，用多个起止不同的 25~45 s 窗口再识别，挑和 Genius 最像的一次。
    识别模型在 50~60 s 的长段里会把含糊、像合唱的一整段丢掉（BZRP 3:31~3:55 三遍都是空的，
    单截 3:25~4:00 就听得出「A ti te quedé grande… igualita que tú」）。补出来的词并到第一遍里，照常对 Genius；
    Genius 里没有的句子没有别的遍确认，不会进字幕。返回补了哪些段落。"""
    from .gap_fill import voiced_ratio
    dur = len(y) / sr
    have = sorted((w["s"], w["e"]) for ws in reads for w in ws)
    holes, t = [], 0.0
    for nxt, end in have + [(dur, dur)]:
        if nxt - t >= HOLE_MIN:
            # 空档里人声连续明显的部分（每 2 s 一格，有声比例 ≥ 0.5）
            a = None
            for x in np.arange(t, nxt, 2.0):
                v = voiced_ratio(y, sr, x, min(nxt, x + 2.0)) >= 0.5
                if v and a is None:
                    a = x
                if (not v or x + 2.0 >= nxt) and a is not None:
                    b = x + 2.0 if v else x
                    if b - a >= HOLE_MIN:
                        holes.append((a, min(b, nxt)))
                    a = None
        t = max(t, end)   # 空洞从前一个词结束之后算起：补出来的词不和已经识别到的重叠
    from rapidfuzz import fuzz
    gk = key(" ".join(lines), lang)

    def like(ws):   # 和 Genius 歌词有多像（像的字母数）
        k = key(A3.text_of(ws), lang)
        return len(k) * fuzz.partial_ratio(k, gk) / 100 if len(k) >= 6 else 0.0

    filled = []
    for a, b in holes:
        # 识别结果对截取起止很敏感（BZRP：从 3:26 截起听得出整句，从 3:28 / 3:30 截起是空的）：换几种起止各识别一次，
        # 挑和 Genius 最像的那次
        best = (0.0, [])
        for x in np.arange(a, b, 25.0):
            seg_b = min(b, x + 25.0)
            # 起点差 0.02 s 结果就可能从整句变成空（205.98 空、206.0 整句），所以多试几个窗口，试到够像为止
            for d0, d1 in ((-7, 1), (-5, 5), (-3, 3), (-1, 7), (-6, 6), (-4, 10), (-2, 2), (-8, 4), (0, 8), (-9, 9), (-3, 12), (-6, 0)):
                x0, x1 = max(0.0, round((x + d0) * 2) / 2), min(dur, round((seg_b + d1) * 2) / 2)
                ws = [w for w in A3.asr_words(y[int(x0 * sr):int(x1 * sr)], sr, key_, cache, t0=x0) if max(a - 0.2, x - 1) <= w["s"] < seg_b + 1]
                sc = like(ws)
                if sc > best[0]:
                    best = (sc, ws)
                if sc >= 0.5 * len(key(A3.text_of(ws), lang)) and sc >= 20:   # 够像了，不用再试
                    break
        got = sorted({(w["s"], w["w"]): w for w in best[1]}.values(), key=lambda w: w["s"])
        if got:
            for w in got:
                w["src"], w["hole"] = 1, True
            reads[0][:] = sorted(reads[0] + got, key=lambda w: w["s"])
            filled.append((round(a, 1), round(b, 1), A3.text_of(got)))
    return filled


# ---------------------------------------------------------------- 3. 定文字（短语 + 动态规划 + 对 Genius）

def half(line):
    return A3.half(line)


@lru_cache(maxsize=None)
def shows(line):
    """一句 Genius 可以显示成：整句 / 唱两遍的半句 / 逗号前的前半句（≥ 4 个词，后面还剩 ≥ 2 个词）。
    BZRP 1:30「Esto es pa' que te mortifique', mastique' y trague', trague' y mastique'」现场只唱到第三个逗号前。"""
    out = [line] + ([half(line)] if half(line) else [])
    parts = line.split(",")
    n_all = len(re.findall(r"[^\W\d_]+", line))
    for i in range(1, len(parts)):
        pre = ",".join(parts[:i]).strip()
        n = len(re.findall(r"[^\W\d_]+", pre))
        if n >= 4 and n_all - n >= 2 and pre not in out and not is_interj(",".join(parts[i:]), "en"):
            out.append(pre)
    return out


def match_group(ws, plain, langs):
    """一组词对 Genius：单句 / 唱两遍的半句 / 连续两句（按词拆开）。返回 [(词, 句号, 分, 显示)] 或 [(词, None, 最高分, None)]。"""
    s = A3.text_of(ws)
    best = (0.0, None)
    for k in range(len(plain)):
        lg = langs[k]
        for show in shows(plain[k]):
            sc = score(s, show, lg)
            if sc > best[0]:
                best = (sc, [(ws, k, show)])
        if k + 1 < len(plain) and len(ws) >= 2:
            for cut in range(1, len(ws)):
                a, b = ws[:cut], ws[cut:]
                sa, sb = score(A3.text_of(a), plain[k], lg), score(A3.text_of(b), plain[k + 1], langs[k + 1])
                sc2 = (sa * len(a) + sb * len(b)) / len(ws)
                if min(sa, sb) >= 60 and sc2 >= MATCH and sc2 > best[0]:
                    best = (sc2, [(a, k, plain[k]), (b, k + 1, plain[k + 1])])
    # Genius 写一遍、现场连唱两遍（sobaniirune 1:00「心の中では…寂しいんだよ」×2）：在中间停顿最长处拆成两行
    if best[0] < MATCH and len(ws) >= 4:
        for k in range(len(plain)):
            if score(s, plain[k] + " " + plain[k], langs[k]) >= MATCH:
                lo, hi = len(ws) // 3, len(ws) - len(ws) // 3
                cut = max(range(max(1, lo), max(lo + 1, hi)), key=lambda i: ws[i]["s"] - ws[i - 1]["e"])
                a, b = ws[:cut], ws[cut:]
                sa, sb = score(A3.text_of(a), plain[k], langs[k]), score(A3.text_of(b), plain[k], langs[k])
                if min(sa, sb) >= 60:
                    return [(a, k, round(sa, 1), plain[k]), (b, k, round(sb, 1), plain[k])]
    if best[0] >= MATCH:
        return [(part, k, round(score(A3.text_of(part), show, langs[k]), 1), show) for part, k, show in best[1]]
    return [(ws, None, round(best[0], 1), None)]


def match_all(words, plain, langs, prof, max_group=16, gap=1.5):
    ph = A3.phrases(words)
    n = len(ph)
    best, back, memo = [0.0] + [-1e9] * n, [None] * (n + 1), {}
    for i in range(1, n + 1):
        best[i], back[i] = best[i - 1], (i - 1, None)
        for j in range(i - 1, max(-1, i - 1 - max_group), -1):
            if j < i - 1 and ph[j + 1][0]["s"] - ph[j][-1]["e"] > gap:
                break
            group = [w for p in ph[j:i] for w in p]
            if (j, i) not in memo:
                memo[(j, i)] = match_group(group, plain, langs)
            res = memo[(j, i)]
            if res[0][1] is None:
                continue
            val = sum((sc - 60) * len(part) for part, k, sc, show in res)
            if best[j] + val > best[i]:
                best[i], back[i] = best[j] + val, (j, res)
    out, i = [], n
    while i > 0:
        j, res = back[i]
        out[:0] = res if res is not None else [(ph[i - 1], None, 0.0, None)]
        i = j
    cap = MAX_LINE[prof["script"]]
    merged = []
    for part, k, sc, show in out:
        if merged and k is None and merged[-1][1] is None and merged[-1][0][-1].get("pid") == part[0].get("pid") \
                and units(A3.text_of(merged[-1][0] + part), prof["main"]) <= cap:
            merged[-1] = (merged[-1][0] + part, None, max(merged[-1][2], sc), None)
        else:
            merged.append((part, k, sc, show))
    return merged


def lyric_like(r, genius_keys):
    """这行听到的话在 Genius 全文里有高度相似的一段（≥ 2 个词 / 6 个字母）。"""
    from rapidfuzz import fuzz
    k = key(r["heard"], r["lang"])
    full = genius_keys.get(r["lang"]) or next(iter(genius_keys.values()))
    return len(k.replace(" ", "")) >= 6 and fuzz.partial_ratio(k, full) >= 85


def is_interj(text, lang):
    """整段都是语气词（uh-uh-uh-uh、Oh-eh, oh-eh）。"""
    toks = [t for t in re.split(r"[\s,，、\-!?.()]+", text.lower()) if t]
    allij = set().union(*INTERJ.values())
    return bool(toks) and all(t in allij or re.fullmatch(r"(?:[aeiou]h?)+", t) for t in toks)


LONG = 12   # 一行超过这么多词（日中韩：字数的一半）就在最靠中间的逗号处拆成两行


def split_long(matched, prof):
    """Genius 本身就很长的一句（BZRP「A ti te quedé grande y por eso estás con una igualita que tú, uh-uh-uh-uh」）
    在最靠中间的逗号处拆成两行；听到的词按词数比例分给两行，各自定时间。"""
    out = []
    for part, k, sc, show in matched:
        n = units(show, prof["main"]) if show else 0
        if script_of(prof["main"]) == "cjk":
            n //= 2
        cuts = [m.end() for m in re.finditer(r"[,，、]\s*", show or "")][:-1] if show and show.rstrip()[-1:] in ",，、" else \
            [m.end() for m in re.finditer(r"[,，、]\s*", show or "")]
        if k is None or n <= LONG or not cuts or len(part) < 2:
            out.append((part, k, sc, show))
            continue
        # 逗号后面只剩语气词（…que tú, uh-uh-uh-uh）：留在这一行里（和 Genius 一致），不单独成行；
        # 长度不算这截语气词，还太长才在前面的逗号处拆
        tail = show[cuts[-1]:].strip()
        if is_interj(tail, prof["main"]):
            body = show[:cuts[-1]].strip().rstrip(",，、")
            cuts = cuts[:-1]
            if units(body, prof["main"]) <= LONG + 2 or not cuts:
                out.append((part, k, sc, show))
                continue
        c = min(cuts, key=lambda c: abs(len(show[:c]) - len(show) / 2))
        a, b = show[:c].strip().rstrip(",，、"), show[c:].strip()
        if not a or not b or is_interj(a, prof["main"]) or is_interj(b, prof["main"]):
            out.append((part, k, sc, show))
            continue
        na = round(len(part) * len(a) / (len(a) + len(b)))
        na = min(max(1, na), len(part) - 1)
        out += [(part[:na], k, sc, a), (part[na:], k, sc, b)]
    return out


# ---------------------------------------------------------------- 4. 定时间：每行在三遍里找位置，投票

def locate(row, ws, lang, span=8.0, lo=None, hi=None):
    """在一遍识别里找这行（前后 span 秒内），返回 (开始, 结束) 或 None。
    副歌、口号几秒就重复一次：分数差不多（相差 ≤ 10）的几处里取离这行最近的，不取分最高的。
    lo / hi：只在上一行结束和下一行开始之间找。BZRP 4:39「La suegra y la vecina」另外两遍没听到，
    就找到了前一句「…la vecina a la suegra」，两票压过一票，被拉到 4:35.9。"""
    from rapidfuzz import fuzz
    target = key(row["heard"], lang) or key(row["text"], lang)
    if not target:
        return None
    m = max(1, row["n_words"])
    cands = []
    for i, w in enumerate(ws):
        if abs(w["s"] - row["A"]) > span or (lo is not None and w["s"] < lo) or (hi is not None and w["s"] >= hi):
            continue
        best = (0.0, None)
        for n in range(max(1, m - 2), m + 3):
            seg = ws[i:i + n]
            k = key(A3.text_of(seg), lang) if seg else ""
            sc = fuzz.ratio(target, k) if k else 0
            if sc > best[0]:
                best = (sc, (seg[0]["s"], seg[-1]["e"]))
        if best[0] >= MATCH:
            cands.append(best)
    if not cands:
        return None
    top = max(sc for sc, _ in cands)
    return min((pos for sc, pos in cands if sc >= top - 10), key=lambda p: abs(p[0] - row["A"]))


def vote(row, mms_ok):
    """A1 / A2 / A3 / B / C 投票：相差 ≤ AGREE 的算一伙，取人数最多的一伙。"""
    src = {k: row.get(k) for k in ("A1", "A2", "A3", "B") if row.get(k) is not None}
    if mms_ok and row.get("C") is not None:
        src["C"] = row["C"]
    if not src:
        return None, "bad", "五个来源都找不到这行的位置", []
    items = sorted(src.items(), key=lambda x: x[1])
    best = []
    for i in range(len(items)):
        grp = [x for x in items if items[i][1] <= x[1] <= items[i][1] + AGREE]
        key_ = (len(grp), any(k == "C" for k, _ in grp), any(k.startswith("A") for k, _ in grp))
        if not best or key_ > best[0]:
            best = [key_, grp]
    grp = best[1]
    names = [k for k, _ in grp]
    asr = [v for k, v in grp if k.startswith("A")]
    left_out = [f"{k} 差 {abs(v - grp[0][1]):.1f}s" for k, v in items if k not in names]
    if len(grp) >= 2:
        if "C" in names:
            t, how = src["C"], "C"
        elif asr:
            t, how = float(np.median(asr)), "A 中位"
        else:
            t, how = src["B"], "B"
        note = f"{'、'.join(names)} 一致，用 {how}" + (f"；{'，'.join(left_out)}，没用" if left_out else "")
        return t, "ok", note, names
    all_asr = [v for k, v in src.items() if k.startswith("A")]
    t = float(np.median(all_asr)) if all_asr else items[0][1]
    return t, "warn", f"各来源都不一致（{'，'.join(f'{k} {v:.1f}' for k, v in items)}），用三遍识别的中位数", []


# ---------------------------------------------------------------- 讲话还是唱

SUNG = 0.70   # 稳定音占比 ≥ 这个算在唱（实测：讲话 0.42~0.63，旋律唱段 0.73~0.91）


class Pitch:
    """整首人声的音高曲线（pyin，10 ms 一帧），算一次存到 reports/pitch.npz。
    稳定帧 = 音高停在一个音上（连续 ≥ 120 ms、相邻帧差 < 25 音分）：唱歌会停在音上，说话 / 说唱音高一直在滑。"""

    def __init__(self, y, sr, cache):
        import librosa
        sig = f"{len(y)}:{float(np.abs(y[::997]).sum()):.4f}"
        if cache.exists():
            z = np.load(cache, allow_pickle=False)
            if str(z["sig"]) == sig:
                self.voiced, self.steady = z["voiced"], z["steady"]
                return
        f0, vf, _ = librosa.pyin(y, fmin=70, fmax=1000, sr=sr, frame_length=1024, hop_length=sr // 100)
        c = 1200 * np.log2(np.where(vf, f0, np.nan) / 55.0)
        steady, run = np.zeros(len(c), bool), 0
        for i in range(1, len(c) + 1):
            if i < len(c) and vf[i] and vf[i - 1] and abs(c[i] - c[i - 1]) < 25:
                run += 1
                continue
            if run >= 12:
                steady[i - run:i] = True
            run = 0
        self.voiced, self.steady = vf.astype(bool), steady
        np.savez(cache, sig=sig, voiced=self.voiced, steady=self.steady)

    def ratio(self, a, b):
        i, j = int(a * 100), int(b * 100)
        v = self.voiced[i:j].sum()
        return float(self.steady[i:j].sum() / v) if v >= 20 else 0.0


PITCH = None


def steady_ratio(y, sr, a, b):
    """[a, b] 秒里稳定帧占有声帧的比例（用整首算好的音高曲线）。"""
    return PITCH.ratio(a, b)


class Stereo:
    """人声左右声道的相关性（0.5 s 一帧、前后 2 s 窗口），存到 reports/stereo.npz。
    歌手的声音来自话筒、混在正中间，左右几乎一样；观众合唱是现场环境话筒收的，左右差别大，相关性低。"""

    def __init__(self, path, cache):
        import soundfile as sf
        sig = f"{path.stat().st_size}:{path.stat().st_mtime_ns}"
        if cache.exists():
            z = np.load(cache, allow_pickle=False)
            if str(z["sig"]) == sig:
                self.corr = z["corr"]
                return
        y, sr = sf.read(str(path), always_2d=True)
        if y.shape[1] < 2:
            self.corr = np.full(int(len(y) / sr * 2) + 1, np.nan)
        else:
            L, R, hop, win = y[:, 0], y[:, 1], sr // 2, 2 * sr
            out = []
            for c in range(0, len(L), hop):
                l, r = L[max(0, c - win):c + win], R[max(0, c - win):c + win]
                out.append(np.corrcoef(l, r)[0, 1] if len(l) > sr and np.sqrt((l ** 2).mean()) > 0.01 else np.nan)
            self.corr = np.array(out)
        np.savez(cache, sig=sig, corr=self.corr)

    def at(self, a, b):
        x = self.corr[int(a * 2):int(b * 2) + 1]
        return float(np.nanmedian(x)) if np.isfinite(x).any() else np.nan

    def median(self):
        return float(np.nanmedian(self.corr)) if np.isfinite(self.corr).any() else np.nan


STEREO = None
CROWD_DROP = 0.15   # 左右相关性比本首中位低这么多、而且这行没有很准地对上 Genius（< 88 分）：标「观众合唱?」


RAP_STEADY = 0.45                       # 这一行附近（至少 4 s）稳定度低于这个、
RAP_RATE = {"latin": 2.0, "cjk": 5.0}   # 而且每秒词数（日中韩：字数）不低于这个，算说唱


def style_of(r, script):
    """这一行是唱 / 说唱 / 讲话 / 观众合唱。"""
    if r.get("speech"):
        return "speech", None
    mid, hw = (r["s"] + r["e"]) / 2, max(2.0, (r["e"] - r["s"]) / 2)
    c, med = STEREO.at(mid - hw, mid + hw), STEREO.median()
    if np.isfinite(c) and np.isfinite(med) and c <= med - CROWD_DROP and (not r["genius"] or r["score"] < 88):
        return "crowd", round(c - med, 2)
    mid, half_w = (r["s"] + r["e"]) / 2, max(2.0, (r["e"] - r["s"]) / 2)
    st = PITCH.ratio(mid - half_w, mid + half_w)
    rate = units(r["text"], r["lang"]) / max(0.3, r["e"] - r["s"])
    rap = st < RAP_STEADY and rate >= RAP_RATE[script_of(r["lang"])]
    return ("rap" if rap else "sing"), round(st, 2)


STREAK = 3       # 连续这么多行对上 Genius 才算进入歌词范围
TALK = 0.50      # 开头 / 结尾单独一块（含对上 Genius 的行）整块稳定度低于这个算对话
BLOCK_GAP = 6.0  # 和后面隔着这么久没字幕，才算单独一块


def head_block(rows, dur):
    """开头到第一个 ≥ BLOCK_GAP 空档之间的行；要在全曲前 30% 内、≥ 3 行、≥ 5 s，否则 None。"""
    blk = rows[:1]
    for a, b in zip(rows, rows[1:]):
        if b["s"] - a["e"] >= BLOCK_GAP:
            break
        blk.append(b)
    if len(blk) == len(rows) or len(blk) < 3 or blk[-1]["e"] > 0.3 * dur or blk[-1]["e"] - blk[0]["s"] < 5:
        return None
    return blk


def tail_block(rows, dur):
    blk = head_block([{**r, "s": dur - r["e"], "e": dur - r["s"], "_r": r} for r in reversed(rows)], dur)
    return [x["_r"] for x in reversed(blk)] if blk else None


def tidy(text):
    """显示用：整行包在括号里的去掉外层括号；括号不配对（逗号前半句切出来的「(Pa' tipos como tú」）去掉括号。"""
    t = text.strip()
    if t.startswith("(") and t.endswith(")") and t.count("(") == 1:
        t = t[1:-1].strip()
    if t.count("(") != t.count(")"):
        t = t.replace("(", "").replace(")", "").strip()
    return t


def reindex(live, plain, lines):
    """同一句在 Genius 里出现好几次（BZRP「Pa' tipos como tú」在第 0、2、11、27、48、52 行）：按顺序选
    「上一行之后最近的那一次」。不然取到开头带括号的第 0 行，它的下一句是「Oh-oh」，按顺序补就补错了。"""
    prev = -1
    for r in live:
        k = r.get("k")
        if k is None or not r["genius"]:
            continue
        kk = key(plain[k], r["lang"])
        same = [x for x in range(len(plain)) if key(plain[x], r["lang"]) == kk]
        if len(same) > 1:
            after = [x for x in same if x > prev]
            pick = prev + 1 if prev + 1 in same else (min(after) if after else min(same))
            if pick != k:
                r["k"], r["genius"] = pick, lines[pick]
        prev = r["k"]


SEQ_MAX = 4     # 两句锚点之间最多补这么多句
SEQ_GAP = 3.0   # 锚点后面的唱段离锚点不超过这么久，才按顺序接下一句


def seq_fill(live, lines, plain, langs):
    """按 Genius 顺序补：对上 Genius 的两句（锚点）中间夹着对不上的唱段，Genius 里两句之间正好缺几句，就按顺序填进去；
    最后一个锚点后面紧跟着对不上的唱段，填它的下一句。观众合唱、咬字含糊时识别出来是走样的文字
    （BZRP 4:38「La suegra y la vecina」= Con la prensa en la puerta…，4:46「Más dura」= Las mujeres ya no lloran…）。"""
    i = 0
    while i < len(live):
        a = live[i]
        if a.get("k") is None or not a["genius"]:
            i += 1
            continue
        j = i + 1
        while j < len(live) and not live[j]["genius"] and not live[j].get("speech"):
            j += 1
        gap_rows = live[i + 1:j]
        nb = live[j] if j < len(live) and live[j]["genius"] and live[j].get("k") is not None else None
        if not gap_rows or gap_rows[0]["s"] - a["e"] > SEQ_GAP:
            i = max(j, i + 1)
            continue
        if nb is not None and 1 <= nb["k"] - a["k"] - 1 <= SEQ_MAX:
            want = list(range(a["k"] + 1, nb["k"]))
        elif nb is None or nb["k"] - a["k"] - 1 > SEQ_MAX or nb["k"] <= a["k"]:
            want = [a["k"] + 1] if a["k"] + 1 < len(lines) else []
            # 没有下一个锚点（或者锚点跳得很远）：只接紧挨着的一段唱（中间不断开超过 SEQ_GAP）
            cut = 1
            while cut < len(gap_rows) and gap_rows[cut]["s"] - gap_rows[cut - 1]["e"] <= SEQ_GAP:
                cut += 1
            gap_rows = gap_rows[:cut]
        else:
            want = []
        # 纯语气词行（Oh-oh）不拿来补：没有下一个锚点时跳过它接后面的实词句
        if nb is None or not (1 <= nb["k"] - a["k"] - 1 <= SEQ_MAX):
            nk = a["k"] + 1
            while nk < len(lines) and is_interj(plain[nk], langs[nk]):
                nk += 1
            want = [nk] if want and nk < len(lines) else []
        want = [k for k in want if not is_interj(plain[k], langs[k])]
        # 附近已经有这句了（比如副歌刚唱过）就不补
        want = [k for k in want if not any(r.get("k") == k and abs(r["s"] - a["s"]) < 15 for r in live)]
        if want and gap_rows:
            # 唱段按时间均分成 len(want) 组（行比句子少：后面的句子不补）
            n = min(len(want), len(gap_rows))
            groups = [gap_rows[round(g * len(gap_rows) / n):round((g + 1) * len(gap_rows) / n)] for g in range(n)]
            for k, grp in zip(want, groups):
                r0 = grp[0]
                heard = " / ".join(x["heard"] for x in grp)
                r0.update({"genius": lines[k], "text": plain[k], "k": k, "lang": langs[k], "e": grp[-1]["e"], "verdict": "seq",
                           "note": r0.get("note", "") + f"；按 Genius 顺序：上一句是「{a['genius']}」，这里该唱「{lines[k]}」"
                                   f"（听到的是「{heard}」，没对上；多半是观众合唱、咬字含糊）"})
                for x in grp[1:]:
                    x["merged"] = True
            live[:] = [r for r in live if not r.get("merged")]
            j = live.index(nb) if nb is not None and nb in live else len(live)
        i = max(j, i + 1)
    # 识别复读：只有一遍听到、听到的和上一行一样，Genius 里上一句的下一句却是别的句子 → 改成下一句
    # （BZRP 3:08 第二遍又听到一遍「¿Quién es Nombre la persona buena」，其实唱的是「Claramente no es como suena」）
    for x in range(1, len(live)):
        a, r = live[x - 1], live[x]
        if not (a["genius"] and r["genius"] and a.get("k") is not None and r.get("k") is not None):
            continue
        heard_by = sum(1 for n in (1, 2, 3) if r.get(f"A{n}") is not None)
        nk = a["k"] + 1
        if heard_by <= 1 and nk < len(lines) and r["k"] != nk and plain[nk] != plain[r["k"]] \
                and score(r["heard"], a["heard"], r["lang"]) >= 85 and r.get("verdict") != "patch":
            r["note"] = r.get("note", "") + (f"；只有一遍听到、和上一行听到的一样（识别复读），按 Genius 顺序上一句"
                                             f"「{a['genius']}」后面是「{lines[nk]}」，改成这句")
            r.update({"genius": lines[nk], "text": plain[nk], "k": nk, "lang": langs[nk], "verdict": "seq"})
    # 补上的句子比听到的碎片长：结尾往后延到「按字数估的长度」，不越过下一行
    for x, r in enumerate(live):
        if r.get("verdict") == "seq":
            nxt = live[x + 1]["s"] - 0.1 if x + 1 < len(live) else r["e"] + 5
            r["e"] = max(r["e"], min(nxt, r["s"] + 0.4 * units(r["text"], r["lang"])))


# ---------------------------------------------------------------- 主流程

def run(song_dir, lyrics, out_dir, hint_lang=None):
    import librosa
    import llm
    import pysubs2
    from qwen_asr import SR
    from .gap_fill import clean_parens, voiced_ratio

    d = song_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    llm.load_env()
    key_ = os.environ["ALIYUN_BAILIAN_API_KEY"]
    cache = d / "reports" / "asr31_cache.json"
    y, _ = librosa.load(str(d / "vocals.wav"), sr=SR, mono=True)
    dur = len(y) / SR
    global PITCH
    PITCH = Pitch(y, SR, d / "reports" / "pitch.npz")
    global STEREO
    STEREO = Stereo(d / "vocals.wav", d / "reports" / "stereo.npz")
    lines = [l.strip() for l in lyrics if l.strip()]
    plain = [clean_parens(l) for l in lines]

    reads = [A3.read_song(y, SR, key_, cache), A3.read_song(y, SR, key_, cache, phase=A3.MAX_PART / 2),
             A3.read_song(y, SR, key_, cache, phase=A3.MAX_PART / 4)]
    for k, ws in enumerate(reads, 1):
        for w in ws:
            w["src"] = k
    holes = fill_holes(y, SR, key_, cache, reads, lines, hint_lang or Counter(line_lang(l) for l in lines).most_common(1)[0][0])
    prof = profile(lines, reads, hint_lang)
    langs = prof["per_line"]
    words = pick_reads(reads, lines, prof)

    rows = []
    for part, k, sc, show in split_long(match_all(words, plain, langs, prof), prof):
        heard = A3.text_of(part)
        lg = langs[k] if k is not None else line_lang(heard, prof["main"])
        src = Counter(w["src"] for w in part).most_common(1)[0][0]
        rows.append({"src": src, "heard": heard, "genius": lines[k] if k is not None else "", "score": sc, "lang": lg,
                     "text": show if k is not None else re.sub(r"[.?!,]+$", "", heard[0].upper() + heard[1:]),
                     "A": part[0]["s"], "A_end": part[-1]["e"], "n_words": len(part), "k": k})

    # Genius 里没有的行：另外两遍至少一遍也听到、且像词才算数
    for r in rows:
        if r["genius"]:
            continue
        if not word_like(r["heard"], r["lang"]):
            r["unconfirmed"], r["why"] = True, "太短、不像词"
            continue
        others = [locate(r, ws, r["lang"]) for k, ws in enumerate(reads, 1) if k != r["src"]]
        if not any(others):
            r["unconfirmed"], r["why"] = True, "另外两遍在这里都没听到这句"

    # 每行在三遍里各找一次位置（不越过前后两行：字幕是按顺序唱的）
    order = sorted([r for r in rows if not r.get("unconfirmed")], key=lambda r: r["A"])
    for i, r in enumerate(order):
        lo = order[i - 1]["A_end"] - 0.5 if i else None
        hi = order[i + 1]["A"] + 0.5 if i + 1 < len(order) else None
        for k, ws in enumerate(reads, 1):
            pos = (r["A"], r["A_end"]) if k == r["src"] else locate(r, ws, r["lang"], lo=lo, hi=hi)
            r[f"A{k}"] = round(pos[0], 2) if pos else None
            r[f"A{k}_end"] = round(pos[1], 2) if pos else None
    live = [r for r in rows if not r.get("unconfirmed")]
    cache_f = d / "reports" / "dense_cache.json"
    windows = sorted((float(k), v) for k, v in json.loads(cache_f.read_text()).items()) if cache_f.exists() else []
    prof["windows"] = bool(windows)
    A3.engine_b(live, windows)
    if prof["mms"]:
        lat = [r for r in live if r["lang"] in LATIN]
        A3.engine_c(lat, y, SR, prof["main"] if prof["main"] in LATIN else "en")
    for r in live:
        mms_ok = r["lang"] in LATIN and prof["mms"]
        t, verdict, note, names = vote(r, mms_ok)
        r["s"], r["verdict"], r["note"], r["agree"] = t, verdict, note, names
        if t is None:
            continue
        if r.get("C") is not None and mms_ok and "C" in names and r.get("C_end"):
            r["e"] = r["C_end"]
        else:
            ends = [r[f"A{k}_end"] for k in (1, 2, 3) if r.get(f"A{k}") is not None and abs(r[f"A{k}"] - t) <= AGREE]
            r["e"] = float(np.median(ends)) if ends else t + max(0.6, r["A_end"] - r["A"])
    live = [r for r in live if r.get("s") is not None]
    live.sort(key=lambda r: r["s"])

    # 句首拖腔的语气词（ASR 听不出）：开头往前补
    for i, r in enumerate(live):
        if not r["genius"]:
            continue
        lead = []
        for w in re.split(r"[\s,、，]+", re.sub(r"\([^)]*\)", " ", r["text"]).strip()):
            parts = [x for x in w.lower().split("-") if x]
            if parts and all(x in INTERJ.get(r["lang"], set()) for x in parts):
                lead += parts
            else:
                break
        heard = {w.lower() for w in re.findall(r"[^\W\d_]+", r["heard"])}
        n = sum(1 for x in lead if x not in heard)
        if n:
            per = LEAD_PER.get(r["lang"], LEAD_PER["latin"])
            prev_end = live[i - 1]["e"] if i else 0.0
            new = max(prev_end + 0.05, r["s"] - per * n)
            if new < r["s"] - 0.1:
                r["note"] += f"；句首「{' '.join(lead)}」ASR 没听出来，开头往前补 {r['s'] - new:.1f}s"
                r["s"] = new

    # 查漏：有人声没字幕的地方
    patches, misses = [], []
    bounds = [(0.0, 0.0)] + [(r["s"], r["e"]) for r in live] + [(dur, dur)]
    for (_, g0), (g1, _) in zip(bounds, bounds[1:]):
        if g1 - g0 < 2.0 or voiced_ratio(y, SR, g0, g1) < 0.4:
            continue
        got = [[w for w in ws if g0 - 0.3 <= w["s"] < g1] for ws in reads]
        texts = [A3.text_of(ws) for ws in got]
        if not any(texts):
            continue
        near = [r for r in live if abs(r["s"] - g0) < 10 or abs(r["s"] - g1) < 10]
        lg = prof["main"]
        # 听到的就是附近某行：只是时间不一致，投票已经处理
        if any(t and any(score(t, r["heard"], r["lang"]) >= MATCH or score(t, r["text"], r["lang"]) >= MATCH for r in near) for t in texts):
            continue
        # 两遍在同一位置都听到 → 补进字幕
        pair = [(i, j) for i in range(3) for j in range(i + 1, 3) if texts[i] and texts[j] and score(texts[i], texts[j], lg) >= MATCH]
        if pair:
            i, j = pair[0]
            for part, k, sc, show in match_all(got[i], plain, langs, prof):
                heard = A3.text_of(part)
                plg = langs[k] if k is not None else line_lang(heard, lg)
                if k is None and not word_like(heard, plg):
                    continue
                patches.append({"src": i + 1, "k": k, "heard": heard, "genius": lines[k] if k is not None else "", "score": sc,
                                "lang": plg, "text": show if k is not None else heard[0].upper() + heard[1:],
                                "s": part[0]["s"], "e": part[-1]["e"], "A": part[0]["s"], "A_end": part[-1]["e"],
                                f"A{i + 1}": round(part[0]["s"], 2), f"A{j + 1}": round(part[0]["s"], 2),
                                "verdict": "patch", "agree": [f"A{i + 1}", f"A{j + 1}"],
                                "note": f"挑中的那遍漏了，第{'一二三'[i]}遍和第{'一二三'[j]}遍都听到"})
        else:
            best = max(texts, key=len)
            if word_like(best, lg):
                misses.append({"s": g0, "e": g1, "heard": best})
    live = sorted(live + patches, key=lambda r: r["s"])

    # 讲话：Genius 里没有、语速快，或在歌词开始前 / 结束后的长段落
    # 歌词从哪开始、到哪结束：只认「连续 ≥ STREAK 行都对上 Genius」的段落。范围之外零星对上的（前后都不是歌词）不算歌词，
    # 用听到的原话，并进旁边的讲话：Lose Yourself 结尾致谢里「you」对成「Yo」、「man We love you」对成
    # 「Mom, I love you, but this trailer's got」的前半句，把歌词结束点拖到了 5:06，致谢就没被判成讲话
    genius_keys = {lg: key(" ".join(plain), lg) for lg in set(langs) | {prof["main"]}}
    streaks, cur = [], []
    for r in live:
        if r["genius"]:
            cur.append(r)
        else:
            if cur:
                streaks.append(cur)
            cur = []
    if cur:
        streaks.append(cur)
    solid = [x for x in streaks if len(x) >= STREAK]
    first, last = (solid[0][0]["s"], solid[-1][-1]["e"]) if solid else (dur, 0.0)
    for x in streaks:
        if len(x) >= STREAK or not (x[-1]["e"] <= first + 0.5 or x[0]["s"] >= last - 0.5):
            continue
        # 周围（前后各 2 行）Genius 里没有的行大多也像歌词：是在唱（观众合唱、咬字含糊），不是讲话，保留匹配
        # （BZRP 结尾「A ti pues como tú」= Pa' tipos como tú，周围「A ti te quedará / Por suerte」也像歌词）
        i0, i1 = live.index(x[0]), live.index(x[-1])
        around = [r for r in live[max(0, i0 - 2):i0] + live[i1 + 1:i1 + 3] if not r["genius"]]
        if around and sum(lyric_like(r, genius_keys) for r in around) * 2 >= len(around):
            continue
        for r in x:
            # 只去掉「弱」的零星匹配：一两个词的短句、只对上半句 / 前半句的、分数不高的；完整对上一整句的保留
            # （She Wolf 结尾「There's a she-wolf in the closet」是真歌词，前后是对观众喊话）
            full = r["text"] in (clean_parens(r["genius"]), r["genius"])
            if r["verdict"] == "patch" or (full and units(r["text"], r["lang"]) >= 3 and r["score"] >= 85):
                continue
            r["note"] += f"；对上的「{r['genius']}」在歌词范围之外、前后都不是歌词，不算歌词，用听到的原话"
            r["genius"], r["text"] = "", re.sub(r"[.?!,]+$", "", r["heard"][0].upper() + r["heard"][1:])
    reindex(live, plain, lines)
    seq_fill(live, lines, plain, langs)
    for r in live:
        r["text"] = tidy(r["text"])
    run_, runs = [], []
    for r in live:
        if r["genius"]:
            if run_:
                runs.append(run_)
            run_ = []
        else:
            run_.append(r)
    if run_:
        runs.append(run_)
    for run_ in runs:
        n = sum(units(r["heard"], r["lang"]) for r in run_)
        before, after = run_[-1]["e"] <= first + 0.5, run_[0]["s"] >= last - 0.5
        # 只按「在歌词开始前 / 结束后」判：按语速判会把说唱、快歌（BZRP 1:30、Hips Don't Lie 2:37）当成讲话
        if not ((before or after) and n >= 5):
            continue
        # 和 Genius 全文高度相似的行是在唱歌词（现场只唱半句、或断在别处：Empire「Siempre resulta… / Cuando hay que hablar de dos」）
        run_ = [r for r in run_ if not lyric_like(r, genius_keys)]
        if not run_:
            continue
        # 歌词外、Genius 里没有的也可能是在唱（hkt48 开头清唱的歌词版本和 Genius 不一样）：听音高稳不稳
        st = steady_ratio(y, SR, run_[0]["s"], run_[-1]["e"])
        where = "开始前" if before else "结束后"
        for r in run_:
            if st >= SUNG:
                r["note"] = r.get("note", "") + f"；歌词{where}、Genius 里没有，但音高稳（{st:.2f}），是在唱，不算讲话"
            else:
                r["speech"] = True
                r["note"] = r.get("note", "") + f"；歌词{where}、Genius 里没有、音高一直在滑（{st:.2f}），归为讲话"

    # 开头 / 结尾单独一块（和后面隔着 ≥ 6 s 没人声字幕的伴奏），整块音高一直在滑：是对话，即使 Genius 收录了
    # （sobaniirune 开头「久しぶり / 元気？…」Genius 里有，稳定度 0.24；实测讲话 0.24~0.45、开头在唱的 0.56~0.75）
    for blk in (head_block(live, dur), tail_block(live, dur)):
        if not blk or all(r.get("speech") for r in blk):
            continue
        st = steady_ratio(y, SR, blk[0]["s"], blk[-1]["e"])
        if st < TALK:
            for r in blk:
                if not r.get("speech"):
                    r["speech"] = True
                    r["note"] = r.get("note", "") + f"；开头 / 结尾单独一段、整段音高一直在滑（{st:.2f}），是对话，归为讲话"

    # 显示时间
    for i, r in enumerate(live):
        nxt = live[i + 1]["s"] if i + 1 < len(live) else r["e"] + 5
        r["show_e"] = min(max(r["e"] + HOLD, r["s"] + MIN_SHOW), nxt - 0.05)
    prev_e = 0.0
    for r in live:
        r["show_s"] = max(prev_e + 0.05, r["s"] - LEAD, 0.0)
        r["show_e"] = max(r["show_e"], r["show_s"] + 0.3)
        prev_e = r["show_e"]

    lyr, sp = pysubs2.SSAFile(), pysubs2.SSAFile()
    for r in live:
        (sp if r.get("speech") else lyr).events.append(
            pysubs2.SSAEvent(start=int(r["show_s"] * 1000), end=int(r["show_e"] * 1000), text=r["text"]))
    lyr.save(str(out_dir / "lyrics.srt"))
    if sp.events:
        sp.save(str(out_dir / "speech.srt"))
    else:
        (out_dir / "speech.srt").unlink(missing_ok=True)

    table = []
    for r in live:
        src = f"对上 Genius（读音 {r['score']:.0f} 分）" if r["genius"] else "Genius 里没有，用 ASR 文字（另外两遍也听到）"
        if r.get("speech"):
            src = "讲话（Genius 里没有）"
        table.append({"start_ms": round(r["show_s"] * 1000), "end_ms": round(r["show_e"] * 1000), "genius": r["genius"],
                      "qwen": r["heard"], "text": r["text"], "lang": r["lang"], "speech": bool(r.get("speech")),
                      "A1": r.get("A1"), "A2": r.get("A2"), "A3": r.get("A3"), "B": r.get("B"),
                      "C": r.get("C") if r["lang"] in LATIN and prof["mms"] else None, "src": r["src"],
                      "agree": r.get("agree", []), "verdict": r["verdict"], "removed": False,
                      "style": style_of(r, prof["script"])[0], "steady": style_of(r, prof["script"])[1],
                      "strategy": f"第{'一二三'[r['src'] - 1]}遍识别 → {src} → 时间：{r['note']}"})
    for r in rows:
        if r.get("unconfirmed"):
            table.append({"start_ms": round(r["A"] * 1000), "end_ms": round(r["A_end"] * 1000), "genius": "", "qwen": r["heard"],
                          "text": "", "lang": r["lang"], "speech": False, "A1": r.get("A1"), "A2": r.get("A2"), "A3": r.get("A3"),
                          "B": None, "C": None, "src": r["src"], "agree": [], "verdict": "unconfirmed", "removed": True,
                          "strategy": f"Genius 里没有，{r.get('why', '')}，没放进字幕"})
    for m in misses:
        if any(min(m["e"], r["e"]) - max(m["s"], r["s"]) > min(1.0, 0.3 * (m["e"] - m["s"])) for r in live):
            continue   # 后来按 Genius 顺序补上了字幕
        table.append({"start_ms": round(m["s"] * 1000), "end_ms": round(m["e"] * 1000), "genius": "", "qwen": m["heard"],
                      "text": "", "lang": prof["main"], "speech": False, "A1": None, "A2": None, "A3": None, "B": None,
                      "C": None, "src": None, "agree": [], "verdict": "miss", "removed": True,
                      "strategy": "漏：有人声没字幕，只有一遍听到（或几遍听到的不一样），没补进字幕"})
    table.sort(key=lambda r: r["start_ms"])
    (out_dir / "lines.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    prof_out = {k: v for k, v in prof.items() if k != "per_line"}
    prof_out["lines_by_lang"] = dict(Counter(prof["per_line"]))
    prof_out["holes"] = holes
    (out_dir / "profile.json").write_text(json.dumps(prof_out, ensure_ascii=False, indent=1))
    for k, ws in enumerate(reads, 1):
        (out_dir / f"asr_words_{k}.json").write_text(json.dumps(ws, ensure_ascii=False, indent=0))
    return table, prof_out


def translate(src_dir, out_dir, cache, title):
    import subprocess
    from .paths import ROOT, VENV_PY
    cmd = [str(VENV_PY), str(ROOT / "workflow" / "translate_ass.py"), str(out_dir / "lyrics.srt"), "-o", str(out_dir / "lyrics.ass"),
           "--cache", str(cache), "--title", title, "--style", "bzrp"]
    if (out_dir / "speech.srt").exists():
        cmd += ["--speech", str(out_dir / "speech.srt")]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def summary(name, table, prof):
    c = Counter(r["verdict"] for r in table)
    print(f"{name}: 语言 {prof['main']}{'（识别出来是 ' + prof['heard_main'] + '，和歌词不一致）' if prof['mismatch'] else ''}，"
          f"字幕 {sum(1 for r in table if not r['removed'])} 行（一致 {c['ok']}，标黄 {c['warn']}，补 {c['patch']}，顺序 {c['seq']}，"
          f"讲话 {sum(1 for r in table if r.get('speech'))}），漏 {c['miss']}，未确认 {c['unconfirmed']}", flush=True)


def run_song(slug, name):
    import acoustic
    from .paths import Concert
    from .refine import sub_title
    c = Concert(slug)
    it = c.item(name)
    d = c.song_dir(it)
    out = d / "exp_v2"
    os.environ["QWEN_CACHE"] = str(d / "reports" / "qwen_cache.json")
    table, prof = run(d, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")], out)
    translate(d, out, d / "zh_cache.json", sub_title(c, it))
    summary(it["title"], table, prof)


def run_post(name):
    from .paths import ROOT
    d = ROOT / "posts" / name
    out = d / "exp_v2"
    (d / "reports").mkdir(exist_ok=True)
    post = json.loads((d / "post" / f"{name}.json").read_text())
    song = post.get("song") or {}
    lyrics = [l.strip() for l in (d / "lyrics.txt").read_text().splitlines() if l.strip() and not l.startswith("[")]
    table, prof = run(d, lyrics, out)
    translate(d, out, d / "zh_cache.json", f"《{song.get('title') or name}》 {song.get('artist') or ''}".strip())
    summary(name, table, prof)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "workflow"))
    if sys.argv[1] == "post":
        run_post(sys.argv[2])
    else:
        run_song(sys.argv[1], sys.argv[2])
