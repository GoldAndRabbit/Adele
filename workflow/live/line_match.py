# -*- coding: utf-8 -*-
"""
逐行对齐的工具函数（方案见 docs/design/alignment_plan.md 第二版），workflow/song/ 的字幕流程在用。

比 asr_match.py 多的：
  1. 语言档案：整首 + 逐句是什么语言；读音比对、长度、语气词、「像不像词」、拖腔补多少、MMS 用不用都按语言选
     （识别接口的语种参数实测无效：传不传、传错结果都一样，所以只能事后按语言选做法）
  2. 时间投票：每行在三遍识别里各找一次位置（A1 / A2 / A3），加上窗口文本（B）和 MMS（C，只有拉丁字母的句子），
     相差 ≤ 0.5 s 的算一伙，取人数最多的一伙
  3. 查漏：时间不一致的不再列成「漏」；两遍在同一位置都听到的句子补进字幕（标「补」）
  4. 讲话：Genius 里没有、语速快（≥ 2.2 词 / 秒）或在歌词开始前 / 结束后的长段落，归成讲话（黄色字幕，不加 ♪）
"""

import re
from collections import Counter
from functools import lru_cache

import numpy as np

from . import asr_match as AM

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
    heard = Counter(line_lang(AM.text_of(ws[i:i + 20]), main) for ws in reads for i in range(0, len(ws), 20))
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
        text = AM._romaji(text)
    toks = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text)
    ij = INTERJ.get(lang, set())
    keep = [w for w in toks if w.lower() not in ij] or toks
    return " ".join(p for p in (_phon(w, lang) for w in keep) if p)


def score(a, b, lang):
    """按这门语言的读音比，和 asr_match 的通用读音键（西语式同音：w/v/b、z/s、ll/y，语气词表更宽）比，取高的。
    只用按语言的：Dai Dai「Owe owe」对不上「Oh-eh-oh-eh」、BZRP「Sé pa' que te muerdes」对不上「Esto es pa' que te mortifique'」，
    asr_match 的都对得上；只用 asr_match 的：意大利语、日语不准。"""
    from rapidfuzz import fuzz
    pa, pb = key(a, lang), key(b, lang)
    mine = float(fuzz.ratio(pa, pb)) if pa and pb and 0.6 <= len(pa) / len(pb) <= 1.7 else 0.0
    return max(mine, AM.score(a, b))


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
        t = key(AM.text_of(ws), prof["main"])
        return sum(n for k, n in keys if n >= 4 and fuzz.partial_ratio(k, t) >= 80)
    end = max([w["e"] for ws in reads for w in ws] or [0.0])
    out, t = [], 0.0
    while t < end + bin_s:
        cand = [[w for w in ws if t <= w["s"] < t + bin_s] for ws in reads]
        out += max(enumerate(cand), key=lambda x: (cover(x[1]), len(x[1]), -x[0]))[1]
        t += bin_s
    return sorted(out, key=lambda w: w["s"])


HOLE_MIN = 4.0   # 人声明显、三遍都一个字没有的空洞，至少这么长才单独补识别


# ---------------------------------------------------------------- 3. 定文字（短语 + 动态规划 + 对 Genius）

def half(line):
    return AM.half(line)


def lyric_like(r, genius_keys):
    """这行听到的话在 Genius 全文里有高度相似的一段（≥ 2 个词 / 6 个字母）。"""
    from rapidfuzz import fuzz
    k = key(r["heard"], r["lang"])
    full = genius_keys.get(r["lang"]) or next(iter(genius_keys.values()))
    return len(k.replace(" ", "")) >= 6 and fuzz.partial_ratio(k, full) >= 85


LONG = 12   # 一行超过这么多词（日中韩：字数的一半）就在最靠中间的逗号处拆成两行


# ---------------------------------------------------------------- 4. 定时间：每行在三遍里找位置，投票


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


def tidy(text):
    """显示用：整行包在括号里的去掉外层括号；括号不配对（逗号前半句切出来的「(Pa' tipos como tú」）去掉括号。"""
    t = text.strip()
    if t.startswith("(") and t.endswith(")") and t.count("(") == 1:
        t = t[1:-1].strip()
    if t.count("(") != t.count(")"):
        t = t.replace("(", "").replace(")", "").strip()
    if (t.count('"') + t.count("“") + t.count("”")) % 2:   # 引号跨行（Genius 一句话分两行），这一行只剩半个：去掉
        t = t.replace('"', "").replace("“", "").replace("”", "").strip()
    return t


SEQ_MAX = 4     # 两句锚点之间最多补这么多句
SEQ_GAP = 3.0   # 锚点后面的唱段离锚点不超过这么久，才按顺序接下一句


# ---------------------------------------------------------------- 主流程


