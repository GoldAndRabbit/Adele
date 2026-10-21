# -*- coding: utf-8 -*-
"""
空档补词：现场改的词 / 即兴 / 歌词网站上没有的段落（GIRL LIKE ME 马德里场报国家名：Venezolana, ecuatoriana…），
按歌词对齐永远出不了字幕。找出字幕之间明显在唱、却没有字幕的空档，用 Qwen 整段识别实际唱的文字，
MMS 把识别文字在人声上逐词对齐，按标点切成短句补进字幕；识别结果很像某句歌词时用歌词的写法。
补进来的句子记在 reports/asr_lines.json，审核页标「识别」。
"""

import json
import os
import re

import numpy as np

MIN_GAP = 3.0          # 空档至少这么长才补
VOICED = 0.4           # 空档里有人声的比例
MAX_CHUNK = 20.0       # 一次送 Qwen 识别的最长音频
MIN_WORDS = 3          # 识别结果至少这么多个实词
CHANT_GAP = 7.0        # 口号句前面这么短的空档：往前延伸盖住
EARLY = 1.5            # 补进来的句子开头最多可以比空档早这么多（前一句截短）
CTX = 0.8              # 送去识别的音频前后各多带这么多秒：识别段起点卡在一个词中间会认错（Venezolana -> Mezorana）
LYRIC_LIKE = 72        # 识别结果和某句歌词这么像：用歌词的写法（太低会把 Latinas, Las brasileras 改成 Latinas, latinas）
NON_LATIN = re.compile(r"[\u0370-\u03ff\u0400-\u04ff\u0590-\u06ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def lyric_like(heard, lyric):
    """识别文字像不像这句歌词（0~100）：整句字符相似度，或者按词重合——两边各有一半以上的词对得上、
    至少 3 个 3 个字母以上的词（want a girl who shines the candle ≈ I want a girl that shine like glitter）。"""
    from rapidfuzz import fuzz
    a, b = heard.split(), lyric.split()
    if not a or not b:
        return 0.0
    ma = [w for w in a if any(_words_close(w, x) for x in b)]
    mb = [w for w in b if any(_words_close(w, x) for x in a)]
    overlap = 100 * min(len(ma) / len(a), len(mb) / len(b)) if sum(len(w) >= 3 for w in ma) >= 3 else 0.0
    return min(100.0, max(fuzz.ratio(heard, lyric), overlap + 25 if overlap >= 50 else 0.0))


def voiced_ratio(y, sr, s, e):
    seg = y[int(s * sr):int(e * sr)]
    if len(seg) < sr // 2:
        return 0.0
    hop = sr // 20
    k = len(seg) // hop
    db = 20 * np.log10(np.sqrt((seg[:k * hop].reshape(k, hop) ** 2).mean(1)) + 1e-9)
    ref = 20 * np.log10(np.sqrt((y ** 2).mean()) + 1e-9)
    return float((db > ref - 6).mean())


def clean_parens(text):
    """去掉只装语气 / 拟声词的括号：Genius 用括号标和声、喊声（Eh）（Wuh）（Ping）（Prr），不是主唱唱的词。"""
    from .concert_align import INTERJ
    adlib = INTERJ | {"wuh", "ping", "prr", "brr", "hot", "skrt", "woo", "uh-huh"}

    def keep(m):
        words = re.findall(r"[\w'’]+(?:-[\w'’]+)*", m.group(1).lower())
        return "" if words and all(all(p in adlib for p in w.split("-")) for w in words) else m.group(0)
    return re.sub(r"\s*\(([^)]*)\)", keep, text).strip()


def clean_words(text):
    from .concert_align import INTERJ
    words = re.findall(r"[\w'’]+", text.lower())
    return [w for w in words if not all(p in INTERJ for p in w.split("-"))]


def phrases(text):
    """在句号 / 问号 / 感叹号处切成短句；超过 8 个词的再在逗号处切（每段不超过 7 个词），太短的并到前一句。"""
    out = []
    for sent in [x.strip(" ,") for x in re.split(r"[.!?。！？]+", text) if x.strip(" ,")]:
        if len(sent.split()) <= 8:
            out.append(sent)
            continue
        cur = []
        for part in [x.strip() for x in sent.split(",") if x.strip()]:
            if cur and len(" ".join(cur + [part]).split()) > 7:
                out.append(", ".join(cur))
                cur = []
            cur.append(part)
        if cur:
            out.append(", ".join(cur))
    merged = []
    for p in out:
        if merged and len(p.split()) < 2:
            merged[-1] = merged[-1] + ", " + p
        else:
            merged.append(p)
    return merged


def fill(song_dir, srt_path, lang, lyrics):
    import llm
    import pysubs2
    import librosa
    from openai import OpenAI
    from qwen_asr import ENDPOINT, SR, transcribe
    from rapidfuzz import fuzz
    from refine_timing import emission_full, load_model, romanize
    from .concert_align import content

    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
    dur = len(y) / SR
    subs = pysubs2.load(str(srt_path))
    ev = sorted(subs.events, key=lambda e: e.start)
    bounds = [(0.0, 0.0)] + [(e.start / 1000, e.end / 1000) for e in ev] + [(dur, dur)]
    gaps = [(a[1], b[0]) for a, b in zip(bounds, bounds[1:]) if b[0] - a[1] >= MIN_GAP]
    lyric_c = [(l, content(l)) for l in dict.fromkeys(lyrics) if len(content(l).split()) >= 2]
    vocab = {p for l in lyrics for w in clean_words(l) for p in [w, *w.split("-")]}
    model = tokenizer = aligner = em = fr = None
    added = []
    for g0, g1 in gaps:
        if voiced_ratio(y, SR, g0, g1) < VOICED:
            continue
        # 长空档分块识别
        n = max(1, int(np.ceil((g1 - g0) / MAX_CHUNK)))
        edges = np.linspace(g0, g1, n + 1)
        for c0, c1 in zip(edges, edges[1:]):
            r0, r1 = max(0.0, c0 - CTX), min(dur, c1 + CTX)
            text = transcribe(client, y[int(r0 * SR):int(r1 * SR)], "auto") or ""
            words = clean_words(text)
            # 太短 / 同一个词反复喊（Shot! Shot!）不补；但反复喊的是歌词里本来就有的词（Shakira, la la Latina）照补
            in_lyrics = sum(1 for w in words if w in vocab or any(fuzz.ratio(w, v) >= 85 for v in vocab)) / max(1, len(words))
            if len(words) < 2 or (in_lyrics < 0.6 and (len(words) < MIN_WORDS or len(set(words)) / len(words) < 0.5)):
                continue
            if NON_LATIN.search(text) and lang not in ("zh", "ja", "ko", "ru"):
                continue   # 西语 / 英语演唱会里冒出来的中日文、俄文：识别幻听
            if lang not in ("auto", None):
                # 单一语种的歌：再按歌的语种强制识别一遍，两遍对不上就是人群声里的幻听（BZRP 里冒出的法语句子）
                # 词大多在这首的歌词里（Juega como tú sabes / Oe, oe, más fuerte）的不用复核：
                # 英语歌里的西语句子，强制英语识别本来就认不出来
                forced = " ".join(clean_words(transcribe(client, y[int(r0 * SR):int(r1 * SR)], lang) or ""))

                def lyric_words(ph):
                    ws = clean_words(ph)
                    return ws and sum(1 for w in ws if w in vocab or any(fuzz.ratio(w, v) >= 85 for v in vocab)) / len(ws) >= 0.5
                text = ". ".join(ph for ph in phrases(text)
                                 if lyric_words(ph) or (forced and fuzz.partial_ratio(" ".join(clean_words(ph)), forced) >= 70))
                if not text:
                    continue
            if model is None:
                model, tokenizer, aligner = load_model()
                em, fr = emission_full(model, y)
            for ph in phrases(text):
                c = " ".join(clean_words(ph))
                if len(c.split()) < 2:
                    continue
                best = max(lyric_c, key=lambda x: lyric_like(c, x[1]), default=None)
                line = best[0] if best and lyric_like(c, best[1]) >= LYRIC_LIKE else ph[0].upper() + ph[1:]
                added.append((c0, c1, clean_parens(line), ph))
            # 逐词对齐整块识别文字，给每个短句定起止
            block = [x for x in added if x[0] == c0]
            toks = []
            for i, (_, _, _, ph) in enumerate(block):
                toks += [(w, i) for w in romanize(ph, lang)]
            if not toks:
                continue
            a0, a1 = int(r0 * fr), int(r1 * fr)
            try:
                spans = aligner(em[a0:a1], tokenizer(["*"] + [w for w, _ in toks] + ["*"]))[1:-1]
            except Exception:  # noqa: BLE001
                continue
            times = {}
            for sp, (_, i) in zip(spans, toks):
                if sp:
                    t0, t1 = r0 + sp[0].start / fr, r0 + sp[-1].end / fr
                    lo, hi = times.get(i, (t0, t1))
                    times[i] = (min(lo, t0), max(hi, t1))
            for i, x in enumerate(block):
                k = added.index(x)
                if i in times:
                    added[k] = (times[i][0], times[i][1], x[2], x[3])
    # 识别时多带的前后文属于相邻的句子：短句的时间大半落在空档外、或者就是相邻那句歌词，不补
    near = [(e.start / 1000, e.end / 1000, content(e.plaintext)) for e in ev]
    new = []
    for s, e, line, ph in added:
        g = next(((a, b) for a, b in gaps if a - CTX - 1.0 <= s <= b + CTX), None)
        if not g or e <= s:
            continue
        inside = max(0.0, min(e, g[1]) - max(s, g[0])) / (e - s)
        c = " ".join(clean_words(ph))
        dup = any(fuzz.ratio(c, nc) >= 85 for ns, ne, nc in near if nc and ns < e + 1.0 and ne > s - 1.0)
        if inside < 0.6 or dup:
            continue
        # 逐词对齐显示开口比空档早一点（前一句的结尾占住了开头，Venezolana 早 1.2s）：允许早最多 EARLY 秒，前一句截短
        s, e = max(s, g[0] - EARLY), min(e, g[1])
        if s < g[0]:
            for o in ev:
                if s < o.end / 1000 <= g[0] + 0.05 and o.start / 1000 < s - 0.5:
                    o.end = int((s - 0.05) * 1000)
        if e - s >= 0.3:
            new.append((s, e, line, ph))
    for s, e, line, _ in new:
        subs.events.append(pysubs2.SSAEvent(start=int(s * 1000), end=int(e * 1000), text=line))
    subs.sort()
    subs.save(str(srt_path))
    rep = song_dir / "reports" / "asr_lines.json"
    # source：asr = 字幕就是 Qwen 识别的文字；asr_lyric = Qwen 识别的和某句 Genius 歌词很像，字幕用 Genius 的写法
    rep.write_text(json.dumps([{"start": round(s, 2), "end": round(e, 2), "text": line, "heard": ph,
                                "source": "asr" if line == clean_parens(ph[0].upper() + ph[1:]) else "asr_lyric"}
                               for s, e, line, ph in new], ensure_ascii=False, indent=1))
    return len(new)


def _words_close(a, b):
    from rapidfuzz import fuzz
    from .segment import norm
    return fuzz.ratio(norm(a), norm(b)) >= 80


LIST_ITEM_S = 1.2      # 列举句每一项平均唱这么久以上才拆（太快拆了一闪而过）


LEAD = 0.2   # 每句字幕比开口提前出现的秒数（精校最后一步统一加）


INTERJ_LIKE = {"oh", "eh", "ah", "ay", "ayy", "aye", "ayee", "hey", "ole", "olé", "oe", "way", "away", "yeah", "woo", "whoa",
               "na", "la", "uh", "huh", "mm", "hmm", "ooh", "wo", "yo", "e", "o", "a", "i"}


def phon(w):
    """粗略的读音键：西语 / 外来词常见的同音不同写（zangalewa / sangaleva，tsamina / zamina，ll / y，c / k / s）。"""
    from .segment import norm
    w = norm(w).replace("'", "")
    w = w.replace("ts", "s").replace("z", "s").replace("w", "b").replace("v", "b").replace("ll", "y").replace("qu", "k").replace("h", "")
    w = re.sub(r"c(?=[ei])", "s", w).replace("c", "k")
    return re.sub(r"(.)\1+", r"\1", w)


