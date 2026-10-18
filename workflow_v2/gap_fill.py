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


def is_chant(text):
    """同一个词反复喊的口号句：Sha-Sha-Shakira, Sha-Sha-Shakira / La-La-Latinas / Latinas, latinas。"""
    parts = [p for w in re.findall(r"[\w'’]+(?:-[\w'’]+)*", text.lower()) for p in w.split("-")]
    return len(parts) >= 3 and len(set(parts)) / len(parts) <= 0.67


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


def extend_chants(song_dir, srt_path):
    """口号句（Sha-Sha-Shakira, Sha-Sha-Shakira / La-La-Latinas）会连喊好几遍，Qwen 常听成别的词（Shot! Shot!），
    只有后几遍被认出来：它前面紧挨着一段明显在唱、却没有字幕的空档（≤ CHANT_GAP 秒），就把这句往前延伸盖住。
    在逐句复核之后做（复核只看原来识别到的那段，延伸出来的部分 Qwen 本来就听不出）。"""
    import librosa
    import pysubs2
    from qwen_asr import SR
    y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
    subs = pysubs2.load(str(srt_path))
    ev = sorted(subs.events, key=lambda e: e.start)
    done, moved = [], []
    for a, b in zip(ev, ev[1:]):
        g0, g1 = a.end / 1000, b.start / 1000
        if 1.0 <= g1 - g0 <= CHANT_GAP and is_chant(b.plaintext) and voiced_ratio(y, SR, g0, g1) >= 0.5:
            moved.append((b.start / 1000, g0 + 0.1))
            b.start = int((g0 + 0.1) * 1000)
            done.append(round(g0 + 0.1, 2))
    subs.save(str(srt_path))
    # 报告里的句子跟着挪，审核页按起点对得上（复核听到 / 来源）
    for name in ("verify_report.json", "asr_lines.json"):
        f = song_dir / "reports" / name
        if not moved or not f.exists():
            continue
        data = json.loads(f.read_text())
        for x in (data.get("lines", []) if isinstance(data, dict) else data):
            for old, new in moved:
                if abs(x["start"] - old) < 0.3:
                    x["start"] = round(new, 2)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return done


def _words_close(a, b):
    from rapidfuzz import fuzz
    from .segment import norm
    return fuzz.ratio(norm(a), norm(b)) >= 80


def _subseq(small, big):
    it = iter(big)
    return all(any(_words_close(w, x) for x in it) for w in small)


def strip_echo(text, prev_word):
    """去掉识别文字开头「上一句最后一个词的尾音」：和它同词，或者后 4 个字母以上相同（Dominicana -> Americana）。"""
    from .segment import norm
    m = re.match(r"\s*[¡¿]?([\w'’-]+)[\s,.!?]*", text)
    if not prev_word or not m:
        return text
    a, b = norm(m.group(1)), norm(prev_word)
    k = 0
    while k < min(len(a), len(b)) and a[-1 - k] == b[-1 - k]:
        k += 1
    return text[m.end():] if a == b or k >= 4 else text


def adopt_heard(song_dir, srt_path, lyrics, lang):
    """现场改词：逐句复核时 Qwen 听到的和字幕明显不是一回事，换成实际唱的词。两种情况：
      1) 可疑句（复核分没到隐藏线，但不像）里一个实词都对不上，且听到的不是另一句歌词：
         马德里场 GIRL LIKE ME 把「Latinas, latinas」唱成「Americana, Argentina」
      2) 空档补词补进来的句子，复核听到的多了几个词（原来的词按顺序都在）：
         整段识别漏了 ecuatoriana，单句复核听出来了
    ①听三遍（复核那遍、前后各多 CTX 秒、按原起止），去掉上一句尾音的回声，挑被别的遍证实的那遍；②多出来的词带前后文也听到才补；换掉的句子记进 asr_lines.json，审核页标「识别」。"""
    import llm
    import librosa
    import pysubs2
    from openai import OpenAI
    from qwen_asr import ENDPOINT, SR, transcribe
    from rapidfuzz import fuzz
    from .concert_align import content
    from .segment import norm

    rep = song_dir / "reports"
    verify = json.loads((rep / "verify_report.json").read_text()) if (rep / "verify_report.json").exists() else {}
    asr_path = rep / "asr_lines.json"
    asr = json.loads(asr_path.read_text()) if asr_path.exists() else []
    sus = {round(x["start"], 1) for x in verify.get("suspect", []) if not x.get("hidden")}
    lyric_c = [content(l) for l in dict.fromkeys(lyrics) if len(content(l).split()) >= 2]
    subs = pysubs2.load(str(srt_path))
    cands = []
    for ln in verify.get("lines", []):
        heard = (ln.get("heard") or "").strip()
        if not heard or (re.search(r"[㐀-鿿぀-ヿ]", heard) and lang not in ("zh", "ja")):
            continue
        ev = next((e for e in subs.events if abs(e.start / 1000 - ln["start"]) < 0.3 and e.plaintext.strip() == ln["text"]), None)
        if ev is None:
            continue
        prev = max((e for e in subs.events if e.end <= ev.start + 50), key=lambda e: e.end, default=None)
        pw = clean_words(prev.plaintext)[-1] if prev is not None and ev.start - prev.end < 300 and clean_words(prev.plaintext) else ""
        lw, hw = clean_words(ln["text"]), clean_words(strip_echo(heard, pw))
        # 只有纯识别补出来的句子才能加词；已经换成 Genius 原句的（asr_lyric）不动
        from_asr = any(abs(x["start"] - ln["start"]) < 0.4 and x.get("source") == "asr" for x in asr)
        # 换词只换短句 / 口号句（Latinas, latinas）：长句复核听不像，多半是 Qwen 没听清
        # （La tortura「Ay, amor, me duele tanto」-> 「Vuelo pronto, y esto fuera sin mí」）
        bare = re.sub(r"\([^)]*\)", "", ln["text"])   # 括号里的和声回声（Me duele tanto）不算重复
        short = len(content(bare).split()) <= 3 or is_chant(bare)
        # 这句连唱了两遍（Como tú sabe' -> Como tú sabes, como tú sabes）：听到的全是这句的词、长度至少 1.5 倍
        if lw and len(hw) >= 1.5 * len(lw) and all(any(_words_close(w, x) for x in lw) for w in hw) \
                and all(any(_words_close(w, x) for x in hw) for w in lw):
            kind = "repeat"
        elif short and any(len(w) >= 4 for w in hw) and round(ln["start"], 1) in sus and not any(_words_close(a, b) for a in lw for b in hw) \
                and max((fuzz.ratio(content(heard), l) for l in lyric_c), default=0) < LYRIC_LIKE:
            kind = "replace"
        elif from_asr and len(hw) > len(lw) and _subseq(lw, hw):
            kind = "extend"
        else:
            continue
        cands.append((ev, ln, heard, kind, pw, lw))
    if not cands:
        return []
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
    done = []
    for ev, ln, heard, kind, pw, lw in cands:
        s, t = max(0.0, ev.start / 1000 - CTX), ev.end / 1000 + CTX
        ctx = transcribe(client, y[int(s * SR):int(t * SR)], "auto") or ""
        if kind == "repeat":
            # 带前后文再听一遍，这句最长的词也至少出现两次才算
            key = max(lw, key=len)
            if sum(1 for x in clean_words(ctx) if _words_close(key, x)) < 2:
                continue
        elif kind == "extend":
            # 补词漏了词：多出来的词前后文一起听也都听到才补（按整词比：americana 不能算听到了 dominicana）
            again = clean_words(ctx)
            extra = [w for w in clean_words(heard) if not any(_words_close(w, x) for x in lw)]
            if not extra or not all(any(_words_close(w, x) for x in again) for w in extra):
                continue
        else:
            # 换词：三遍（复核那遍、带前后文、按原起止再听）各自去掉上一句尾巴的回声（句子边界还没修好时，
            # 这句开头会带上 Dominicana 的尾音，Qwen 听成 Americana），选「被别的遍证实的词最多、没被证实的最少」的那遍
            exact = transcribe(client, y[int(ev.start / 1000 * SR):int(ev.end / 1000 * SR)], "auto") or ""
            reads = [strip_echo(x, pw) for x in (heard, ctx, exact)]
            words = [clean_words(x) for x in reads]
            best = None
            for i, r in enumerate(reads):
                others = [w for j, ws in enumerate(words) if j != i for w in ws]
                conf = sum(1 for w in words[i] if any(_words_close(w, x) for x in others))
                bad = sum(1 for w in words[i] if len(w) > 3 and not any(_words_close(w, x) for x in others))
                key = (conf - bad, conf, len(words[i]))
                if conf and not bad and (best is None or key > best[0]):
                    best = (key, r)
            if best is None or any(_words_close(a, b) for a in lw for b in clean_words(best[1])):
                continue
            heard = best[1]
        text = re.sub(r"[.!?¡¿。！？]+", "", heard).strip(" ,")
        text = text[0].upper() + text[1:]
        ev.text = text
        done.append({"start": round(ev.start / 1000, 2), "end": round(ev.end / 1000, 2), "text": text,
                     "heard": heard, "was": ln["text"], "source": "adopt"})
        ln["text"], ln["heard"] = text, heard   # 复核栏显示最后确认的那一遍
        verify["suspect"] = [x for x in verify.get("suspect", []) if abs(x["start"] - ln["start"]) >= 0.15]
    if done:
        subs.save(str(srt_path))
        asr = [x for x in asr if not any(abs(x["start"] - d["start"]) < 0.4 for d in done)] + done
        asr_path.write_text(json.dumps(sorted(asr, key=lambda x: x["start"]), ensure_ascii=False, indent=1))
        (rep / "verify_report.json").write_text(json.dumps(verify, ensure_ascii=False, indent=1))
    return done


def rescue_hidden(song_dir, srt_path, lang, lyrics=()):
    """逐句复核只听这句自己的起止，拖长音、句子很短时常听错（「you're lookin' for」只听 1.8s 认成「People」），
    被隐藏后那几秒就没字幕。被隐藏的句子前后各多 CTX 秒再听一遍：这句的实词有六成以上听到了、
    那段时间也没被别的字幕占住，就放回来。片头片尾人群声里误配的句子带上前后文也听不出，照样隐藏。"""
    import llm
    import librosa
    import pysubs2
    from openai import OpenAI
    from qwen_asr import ENDPOINT, SR, transcribe
    from rapidfuzz import fuzz
    from .concert_align import content

    rep = song_dir / "reports" / "verify_report.json"
    if not rep.exists():
        return []
    verify = json.loads(rep.read_text())
    hidden = [x for x in verify.get("suspect", []) if x.get("hidden")]
    if not hidden:
        return []
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
    subs = pysubs2.load(str(srt_path))
    done = []
    for x in hidden:
        ln = next((l for l in verify.get("lines", []) if abs(l["start"] - x["start"]) < 0.15), None)
        if not ln:
            continue
        words = content(ln["text"]).split()
        s, e = ln["start"], ln["end"]
        busy = any(min(e, o.end / 1000) - max(s, o.start / 1000) > 0.2 for o in subs.events)
        if not words or busy or e - s > 8:
            continue
        again = transcribe(client, y[int(max(0.0, s - CTX) * SR):int((e + CTX) * SR)], lang) or ""
        heard = clean_words(again)
        hit = sum(1 for w in words if any(_words_close(w, h) for h in heard))
        # 听到的最像的得是这句：前后文带进来的相邻字幕不算；别的歌词句子更像（No es culpa mía que me critiques
        # 更像「Entendí que no es culpa mía que te critiquen」）就不是这句
        near = {o.plaintext.strip() for o in subs.events if abs(o.start / 1000 - s) < 8}
        own = fuzz.ratio(content(again), content(ln["text"]))
        rival = max((fuzz.ratio(content(again), content(l)) for l in lyrics if l.strip() not in near and l.strip() != ln["text"]),
                    default=0)
        if hit / len(words) < 0.5 or rival > own + 5:
            continue
        subs.events.append(pysubs2.SSAEvent(start=int(s * 1000), end=int(e * 1000), text=ln["text"]))
        ln["heard"] = again
        done.append({"start": s, "text": ln["text"], "heard": again})
    if done:
        subs.sort()
        subs.save(str(srt_path))
        verify["suspect"] = [x for x in verify["suspect"] if not any(abs(x["start"] - d["start"]) < 0.15 for d in done)]
        rep.write_text(json.dumps(verify, ensure_ascii=False, indent=1))
    return done


LIST_ITEM_S = 1.2      # 列举句每一项平均唱这么久以上才拆（太快拆了一闪而过）


def list_items(text):
    """列举句拆成一项一项：逗号分开，「y / e / and」跟着后一项（La brasilera, las bolivianas, y las chilenas ->
    La brasilera / las bolivianas / y las chilenas）。不是列举句（某项超过 3 个词、或没有实词）返回 None。"""
    from .concert_align import content
    parts = [p.strip() for p in re.split(r",\s*", text.strip(" .")) if p.strip()]
    items = []
    for p in parts:
        for i, q in enumerate(re.split(r"\s+(?=(?:y|e|and|&)\s)", p)):
            items.append(q.strip())
    items = [x for x in items if x]
    # 每一项只能是「冠词 / 连词 + 一个词」（La brasilera / y las chilenas / Venezolana）：
    # That here, in this place, you belong / Llegó el momento, caen las murallas 这种普通句子不是列举
    glue = {"la", "las", "el", "los", "lo", "un", "una", "the", "a", "an", "y", "e", "and", "&", "de", "del", "of"}
    core = [[w for w in re.findall(r"[\w'’-]+", x.lower()) if w not in glue] for x in items]
    if len(items) < 2 or any(len(c) != 1 or not content(x) for c, x in zip(core, items)):
        return None
    return items


def split_lists(song_dir, srt_path, lang):
    """报国家名这种列举句（Venezolana, ecuatoriana, puertorriqueña, dominicana）一项一句：
    MMS 在这句的时间段里逐词对齐，每项从它第一个词开口时出现、到下一项开口为止。
    口号句（Latinas, latinas / Sha-Sha-Shakira…）不拆。asr_lines.json / verify_report.json 里的对应句跟着拆。"""
    import librosa
    import pysubs2
    from qwen_asr import SR
    from refine_timing import emission_full, load_model, romanize
    from .segment import norm

    subs = pysubs2.load(str(srt_path))
    todo = []
    for ev in subs.events:
        t = ev.plaintext.strip()
        items = list_items(t)
        if items and not is_chant(t) and len({norm(x) for x in items}) > 1 and (ev.end - ev.start) / 1000 / len(items) >= LIST_ITEM_S:
            todo.append((ev, items))
    if not todo:
        return []
    y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
    model, tokenizer, aligner = load_model()
    em, fr = emission_full(model, y)
    rep = song_dir / "reports"
    asr_path, ver_path = rep / "asr_lines.json", rep / "verify_report.json"
    asr = json.loads(asr_path.read_text()) if asr_path.exists() else []
    verify = json.loads(ver_path.read_text()) if ver_path.exists() else {}
    done = []
    def move_report(old, new):   # 下一句起点挪了：报告里那句跟着挪，审核页才对得上
        for x in verify.get("lines", []) + asr:
            if abs(x["start"] - old) < 0.3:
                x["start"] = round(new, 2)

    for ev, items in todo:
        s, e = ev.start / 1000, ev.end / 1000
        # 紧挨着的下一句一起对齐：报国家名是按拍子一项一项唱的，原来的句子边界常常卡在最后一项中间
        # （Dominicana 103.8-104.7，下一句 Las argentinas 被排在 103.85，实际 105.7 才开口）
        nxt = next((o for o in sorted(subs.events, key=lambda o: o.start) if e - 0.05 <= o.start / 1000 <= e + 0.5), None)
        toks = [(w, i) for i, x in enumerate(items) for w in romanize(x, lang)]
        if nxt is not None:
            toks += [(w, len(items)) for w in romanize(nxt.plaintext, lang)]
        r0, r1 = max(0.0, s - 0.3), (nxt.end / 1000 if nxt is not None else e) + 0.3
        try:
            spans = aligner(em[int(r0 * fr):int(r1 * fr)], tokenizer(["*"] + [w for w, _ in toks] + ["*"]))[1:-1]
        except Exception:  # noqa: BLE001
            continue
        onset = {}
        for sp, (_, i) in zip(spans, toks):
            if sp and i not in onset:
                onset[i] = r0 + sp[0].start / fr
        if any(i not in onset for i in range(len(items))):
            continue
        end = e
        if nxt is not None and len(items) in onset:
            n0, n1 = nxt.start / 1000, nxt.end / 1000
            ns = min(max(onset[len(items)] - 0.1, n0), n1 - 0.5)
            if ns > n0:
                nxt.start = int(ns * 1000)
                move_report(n0, ns)
                end = ns - 0.05
        starts = [s] + [min(max(onset[i] - 0.1, s + 0.3), end - 0.3) for i in range(1, len(items))]
        if any(b - a < 0.3 for a, b in zip(starts, starts[1:])):
            continue
        bounds = starts + [end + 0.05]
        pieces = [(a, b - 0.05, x[0].upper() + x[1:]) for a, b, x in zip(bounds, bounds[1:], items)]
        subs.events.remove(ev)
        for a, b, x in pieces:
            subs.events.append(pysubs2.SSAEvent(start=int(a * 1000), end=int(b * 1000), text=x))
        # 报告里的这句也拆开：复核听到的文字能按同样规则拆成一样多项就逐项对上，否则整句放在第一项
        for ln in [l for l in verify.get("lines", []) if abs(l["start"] - s) < 0.3]:
            heard = list_items(re.sub(r"[.!?¡¿]+", "", ln.get("heard") or "")) or []
            k = verify["lines"].index(ln)
            verify["lines"][k:k + 1] = [{"start": round(a, 2), "end": round(b, 2), "text": x,
                                          "heard": heard[i] if len(heard) == len(pieces) else (ln.get("heard") if i == 0 else "")}
                                         for i, (a, b, x) in enumerate(pieces)]
        for x in [a for a in asr if abs(a["start"] - s) < 0.4]:
            k = asr.index(x)
            asr[k:k + 1] = [{**x, "start": round(a, 2), "end": round(b, 2), "text": t} for a, b, t in pieces]
        done.append({"start": round(s, 2), "text": ev.plaintext, "pieces": [round(a, 2) for a, _, _ in pieces]})
    subs.sort()
    subs.save(str(srt_path))
    if done:
        asr_path.write_text(json.dumps(asr, ensure_ascii=False, indent=1))
        ver_path.write_text(json.dumps(verify, ensure_ascii=False, indent=1))
    return done


LEAD = 0.2   # 每句字幕比开口提前出现的秒数（精校最后一步统一加）


def lead_all(song_dir, srt_path, lead=LEAD):
    """每句字幕统一提前 lead 秒出现：不早于 0、不压到上一句；和下一句首尾相接的（列举句拆开的一项项），
    结尾跟着提前，保持相接。报告里的起点跟着挪，审核页对得上。"""
    import pysubs2
    subs = pysubs2.load(str(srt_path))
    ev = sorted(subs.events, key=lambda e: e.start)
    old = [(e.start / 1000, e.end / 1000) for e in ev]
    new = []
    for i, (s, e) in enumerate(old):
        ns = max(0.0, s - lead, new[-1][1] + 0.05 if new else 0.0)
        contiguous = i + 1 < len(old) and old[i + 1][0] - e < 0.15
        ne = max(ns + 0.3, e - lead if contiguous else e)
        new.append((ns, ne))
    for x, (ns, ne) in zip(ev, new):
        x.start, x.end = int(round(ns * 1000)), int(round(ne * 1000))
    subs.events = ev
    subs.save(str(srt_path))
    for name in ("verify_report.json", "asr_lines.json"):
        f = song_dir / "reports" / name
        if not f.exists():
            continue
        data = json.loads(f.read_text())
        for x in (data.get("lines", []) + data.get("suspect", []) if isinstance(data, dict) else data):
            k = min(range(len(old)), key=lambda j: abs(old[j][0] - x["start"]), default=None)
            if k is not None and abs(old[k][0] - x["start"]) < 0.3:
                x["start"], x["end"] = round(new[k][0], 2), round(new[k][1], 2)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return len(ev)



def snap_runs(song_dir, srt_path, lang, lyrics):
    """空档补词是按空档整段识别的，Qwen 有时听得很乱（BZRP：「¿Dónde queda nuestra culpa」「Me hagan que critique」），
    其实唱的是 Genius 里有的一句。连续的补词句（含被复核隐藏的）连成一段，前后各多 CTX 秒再听一遍：
    某句 Genius 歌词有 3/4 以上的词听到了（至少 4 个词），就把这一段换成这句歌词。"""
    import llm
    import librosa
    import pysubs2
    from openai import OpenAI
    from qwen_asr import ENDPOINT, SR, transcribe

    rep = song_dir / "reports"
    asr_path, ver_path = rep / "asr_lines.json", rep / "verify_report.json"
    if not asr_path.exists() or not ver_path.exists():
        return []
    asr = json.loads(asr_path.read_text())
    verify = json.loads(ver_path.read_text())
    fill = sorted((x for x in asr if x.get("source") == "asr"), key=lambda x: x["start"])
    if not fill:
        return []
    runs = []
    for x in fill:
        if runs and x["start"] - runs[-1][-1]["end"] <= 0.8:
            runs[-1].append(x)
        else:
            runs.append([x])
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
    subs = pysubs2.load(str(srt_path))
    cand = [l for l in dict.fromkeys(x.strip() for x in lyrics) if len(clean_words(l)) >= 4]
    done = []
    for run in runs:
        s, e = run[0]["start"], run[-1]["end"]
        read = transcribe(client, y[int(max(0.0, s - CTX) * SR):int((e + CTX) * SR)], lang) or ""
        rw = clean_words(read)
        best, cov = None, 0.0
        for l in cand:
            lw = clean_words(l)
            c = sum(1 for w in lw if any(_words_close(w, x) for x in rw)) / len(lw)
            if c > cov:
                best, cov = l, c
        if best is None or cov < 0.75:
            continue
        # 这句已经在附近的字幕里了（补词只是重复了相邻句）：不换
        if any(e2.plaintext.strip() == best and abs(e2.start / 1000 - s) < 10 for e2 in subs.events):
            continue
        subs.events = [ev for ev in subs.events if not any(abs(ev.start / 1000 - x["start"]) < 0.3 for x in run)]
        subs.events.append(pysubs2.SSAEvent(start=int(s * 1000), end=int(e * 1000), text=best))
        verify["lines"] = [l for l in verify.get("lines", []) if not any(abs(l["start"] - x["start"]) < 0.3 for x in run)] \
            + [{"start": s, "end": e, "text": best, "heard": read}]
        verify["suspect"] = [x for x in verify.get("suspect", []) if not s - 0.3 <= x["start"] <= e + 0.3]
        asr = [x for x in asr if x not in run] + [{"start": s, "end": e, "text": best, "heard": read, "source": "asr_lyric"}]
        done.append({"start": s, "was": " / ".join(x["text"] for x in run), "text": best})
    if done:
        subs.sort()
        subs.save(str(srt_path))
        verify["lines"].sort(key=lambda l: l["start"])
        asr.sort(key=lambda x: x["start"])
        asr_path.write_text(json.dumps(asr, ensure_ascii=False, indent=1))
        ver_path.write_text(json.dumps(verify, ensure_ascii=False, indent=1))
    return done


def _stem_close(a, b):
    """词形变化也算同一个词：mastique' / masticas、trague' / tragas（前 4 个字母相同、两边都至少 5 个字母）。"""
    from .segment import norm
    a, b = norm(a).strip("'"), norm(b).strip("'")
    return _words_close(a, b) or (len(a) >= 5 and len(b) >= 5 and a[:4] == b[:4])


def fill_expected(song_dir, srt_path, lang, lyrics):
    """补词段换成「本该在这里」的歌词：补词段前后已经对齐的两句 Genius 歌词，在歌词里中间夹着的句子
    就是这里该唱的（DP 因为 Qwen 窗口证据不够跳过了）。补词文字、复核听到的、前后文再听一遍，
    三者合起来能听到其中某句四成以上的词（按词干比，至少 3 个词），就换成这句。
    BZRP：「Te empuja, te muerde… / Traga, te va a quemar」-> 「Esto es pa' que te mortifique', mastique' y trague'…」；
    Dai Dai：副歌连唱两遍，第二遍被听成「Da da, ego / Da li, da li, let's go」-> 「Dai, dai, ikou, dale, allez, let's go」"""
    import llm
    import librosa
    import pysubs2
    from openai import OpenAI
    from qwen_asr import ENDPOINT, SR, transcribe

    rep = song_dir / "reports"
    asr_path, ver_path = rep / "asr_lines.json", rep / "verify_report.json"
    if not asr_path.exists():
        return []
    asr = json.loads(asr_path.read_text())
    verify = json.loads(ver_path.read_text()) if ver_path.exists() else {"lines": [], "suspect": []}
    fill = sorted((x for x in asr if x.get("source") == "asr"), key=lambda x: x["start"])
    if not fill:
        return []
    seq = [l.strip() for l in lyrics]
    subs = pysubs2.load(str(srt_path))
    # 已对齐的 Genius 句子 -> 歌词里的位置（同一句出现多次时按时间顺序往后找）
    anchors, ptr = [], 0
    is_fill = lambda ev: any(abs(ev.start / 1000 - x["start"]) < 0.3 for x in fill)
    for ev in sorted(subs.events, key=lambda e: e.start):
        t = ev.plaintext.strip()
        if is_fill(ev):
            continue
        idx = [k for k, l in enumerate(seq) if clean_parens(l) == t]
        if not idx:
            continue
        k = next((k for k in idx if k >= ptr), idx[0])
        anchors.append((ev.start / 1000, ev.end / 1000, k))
        ptr = k + 1
    runs = []
    for x in fill:
        if runs and x["start"] - runs[-1][-1]["end"] <= 0.8:
            runs[-1].append(x)
        else:
            runs.append([x])
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y = None
    done, used = [], set()
    for run in runs:
        s, e = run[0]["start"], run[-1]["end"]
        after = min((a for a in anchors if a[0] >= e - 0.3), key=lambda a: a[0], default=None)
        if not after:
            continue
        # 前一句取「歌词里在 after 之前」的最近一句：现场顺序和 Genius 不同的句子（BZRP 的 Por acá no vuelva'）跳过
        before = max((a for a in anchors if a[1] <= s + 0.3 and a[2] < after[2] and s - a[1] < 30),
                     key=lambda a: a[1], default=None)
        if not before or after[2] <= before[2] + 1:
            continue
        missing = [k for k in range(before[2] + 1, after[2]) if len(clean_words(seq[k])) >= 3 and k not in used]
        if not missing:
            continue
        if y is None:
            y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
        read = transcribe(client, y[int(max(0.0, s - CTX) * SR):int((e + CTX) * SR)], lang) or ""
        heard = [l.get("heard") or "" for l in verify.get("lines", []) if any(abs(l["start"] - x["start"]) < 0.3 for x in run)]
        words = [w for t in [x["text"] for x in run] + heard + [read] for w in clean_words(t)]
        best, cov, hit = None, 0.0, 0
        for k in missing:
            lw = clean_words(seq[k])
            h = sum(1 for w in lw if any(_stem_close(w, x) for x in words))
            if h / len(lw) > cov:
                best, cov, hit = k, h / len(lw), h
        if best is None or cov < 0.4 or hit < 3:
            continue
        used.add(best)
        text = clean_parens(seq[best])
        subs.events = [ev for ev in subs.events if not any(abs(ev.start / 1000 - x["start"]) < 0.3 for x in run)]
        subs.events.append(pysubs2.SSAEvent(start=int(s * 1000), end=int(e * 1000), text=text))
        verify["lines"] = [l for l in verify.get("lines", []) if not any(abs(l["start"] - x["start"]) < 0.3 for x in run)] \
            + [{"start": s, "end": e, "text": text, "heard": read}]
        verify["suspect"] = [x for x in verify.get("suspect", []) if not s - 0.3 <= x["start"] <= e + 0.3]
        asr = [x for x in asr if x not in run] + [{"start": s, "end": e, "text": text, "heard": read, "source": "asr_lyric"}]
        done.append({"start": s, "was": " / ".join(x["text"] for x in run), "text": text, "cover": round(cov, 2)})
    if done:
        subs.sort()
        subs.save(str(srt_path))
        verify["lines"].sort(key=lambda l: l["start"])
        asr.sort(key=lambda x: x["start"])
        asr_path.write_text(json.dumps(asr, ensure_ascii=False, indent=1))
        ver_path.write_text(json.dumps(verify, ensure_ascii=False, indent=1))
    return done


INTERJ_LIKE = {"oh", "eh", "ah", "ay", "ayy", "aye", "ayee", "hey", "ole", "olé", "oe", "way", "away", "yeah", "woo", "whoa",
               "na", "la", "uh", "huh", "mm", "hmm", "ooh", "wo", "yo", "e", "o", "a", "i"}


def fill_interjections(song_dir, srt_path, lyrics, max_line=6.0):
    """纯语气词的歌词句（Dai Dai 开头的「Oh-eh-oh-eh (Oh-eh), eh-oh-eh」）不参与对齐打分（人群欢呼也能匹配上），
    之前一直没人补，整段没字幕。按歌词顺序找出某句已对齐的歌词前面 / 后面紧挨着的纯语气词句，
    对应的空档里 Qwen 窗口大多听到的也是语气词（Hey, oh, hey / Oh way）、且有人声，就把这几句均匀排进那段。"""
    import librosa
    import pysubs2
    from qwen_asr import SR
    from .concert_align import WIN, HOP, content

    cache_f = song_dir / "reports" / "dense_cache.json"
    if not cache_f.exists():
        return []
    cache = {float(k): v for k, v in json.loads(cache_f.read_text()).items()}
    seq = [l.strip() for l in lyrics]
    pure = [not content(clean_parens(l)) and bool(clean_words(l) or re.search(r"\w", l)) for l in seq]
    subs = pysubs2.load(str(srt_path))
    ev = sorted(subs.events, key=lambda e: e.start)
    y, _ = librosa.load(str(song_dir / "vocals.wav"), sr=SR, mono=True)
    dur = len(y) / SR

    def interj_window(t):
        toks = [p for w in re.findall(r"[\w'’]+(?:-[\w'’]+)*", (cache.get(round(t * 2) / 2) or "").lower()) for p in w.split("-")]
        return bool(toks) and sum(1 for x in toks if x in INTERJ_LIKE) / len(toks) >= 0.6

    anchors = _anchors(song_dir, ev, seq)
    done, used = [], set()
    for i, (e, k) in enumerate(anchors):
        # 紧挨在这句前面的纯语气词句（歌词里往前数，空行已经去掉）
        j = k
        while j - 1 >= 0 and pure[j - 1] and j - 1 not in used:
            j -= 1
        lines = list(range(j, k))
        if not lines:
            continue
        prev_end = max((o.end / 1000 for o in ev if o.end <= e.start), default=0.0)
        g1 = e.start / 1000 - 0.05
        # 从这句往前，连续「听到语气词」的窗口有多长（允许断 1 个窗口）
        t, miss, g0 = g1 - WIN, 0, None
        while t >= max(prev_end, 0.0) - 0.01:
            if interj_window(t):
                g0, miss = t, 0
            else:
                miss += 1
                if miss > 1:
                    break
            t -= HOP
        if g0 is None or g1 - g0 < 1.5 or voiced_ratio(y, SR, g0, g1) < 0.4:
            continue
        g0 = max(g0, g1 - max_line * len(lines), prev_end + 0.05)
        step = (g1 - g0) / len(lines)
        for n, k2 in enumerate(lines):
            s0, s1 = g0 + n * step, g0 + (n + 1) * step - 0.05
            subs.events.append(pysubs2.SSAEvent(start=int(s0 * 1000), end=int(s1 * 1000), text=clean_parens(seq[k2])))
            used.add(k2)
            done.append({"start": round(s0, 2), "end": round(s1, 2), "text": clean_parens(seq[k2])})
    if done:
        subs.sort()
        subs.save(str(srt_path))
    return done


def phon(w):
    """粗略的读音键：西语 / 外来词常见的同音不同写（zangalewa / sangaleva，tsamina / zamina，ll / y，c / k / s）。"""
    from .segment import norm
    w = norm(w).replace("'", "")
    w = w.replace("ts", "s").replace("z", "s").replace("w", "b").replace("v", "b").replace("ll", "y").replace("qu", "k").replace("h", "")
    w = re.sub(r"c(?=[ei])", "s", w).replace("c", "k")
    return re.sub(r"(.)\1+", r"\1", w)


def _phon_close(a, b):
    from rapidfuzz import fuzz
    pa, pb = phon(a), phon(b)
    return len(pa) >= 3 and len(pb) >= 3 and (fuzz.ratio(pa, pb) >= 80 or _stem_close(a, b))


def drop_misplaced(song_dir, srt_path):
    """排序 DP 把只听到一个词的窗口也当成整句的证据（Waka Waka 开头人群喊「¡Vamos!」-> 「Ahora vamos por todo」）：
    逐句复核听到的很短（≤ 2 个词）、这句 3 个以上的实词里只听到 1 个以下，去掉。"""
    import pysubs2
    from .concert_align import content
    rep = song_dir / "reports" / "verify_report.json"
    if not rep.exists():
        return []
    verify = json.loads(rep.read_text())
    subs = pysubs2.load(str(srt_path))
    done = []
    for ln in verify.get("lines", []):
        if not (ln.get("heard") or "").strip():   # 复核识别失败：没有证据，不能当「没听到」
            continue
        words = content(clean_parens(ln["text"])).split()
        heard = clean_words(ln["heard"])
        if len(words) < 3 or len(heard) > 2:
            continue
        hit = sum(1 for w in words if any(_phon_close(w, h) for h in heard))
        if hit > 1:
            continue
        ev = next((e for e in subs.events if abs(e.start / 1000 - ln["start"]) < 0.3 and e.plaintext.strip() == ln["text"]), None)
        if ev is not None:
            subs.events.remove(ev)
            done.append({"start": ln["start"], "text": ln["text"], "heard": ln.get("heard")})
    if done:
        subs.save(str(srt_path))
        verify["lines"] = [l for l in verify["lines"] if not any(abs(l["start"] - d["start"]) < 0.05 for d in done)]
        rep.write_text(json.dumps(verify, ensure_ascii=False, indent=1))
    return done


def _anchors(song_dir, events, seq):
    """已对齐的句子 -> 歌词里的位置（同一句多次出现按时间顺序往后找）；现场改过词的句子按 Genius 原词认。"""
    asr_f = song_dir / "reports" / "asr_lines.json"
    was = {round(x["start"], 1): x["was"] for x in (json.loads(asr_f.read_text()) if asr_f.exists() else []) if x.get("was")}
    out, ptr = [], 0
    for e in events:
        texts = {e.plaintext.strip(), was.get(round(e.start / 1000, 1), "")}
        idx = [k for k, l in enumerate(seq) if clean_parens(l) in texts or l in texts]
        if idx:
            k = next((k for k in idx if k >= ptr), idx[0])
            out.append((e, k))
            ptr = k + 1
    return out


def fill_gaps_expected(song_dir, srt_path, lyrics, min_gap=3.0, max_lines=8):
    """没字幕的空档里补「按歌词顺序本该在这里」的句子：空档前后已对齐的两句 Genius 歌词之间夹着的句子，
    空档里 Qwen 窗口听到了这句的关键词（读音相近也算：Sangaleva = zangalewa、Otra），就把这些句子在
    「最早听到关键词」到空档结束之间均匀排开（Waka Waka 开头「Uh, zangalewa (Otra, otra)」×4）。纯语气词句不在这里补。"""
    import pysubs2
    from .concert_align import WIN, content

    cache_f = song_dir / "reports" / "dense_cache.json"
    if not cache_f.exists():
        return []
    cache = sorted((float(k), v) for k, v in json.loads(cache_f.read_text()).items())
    seq = [l.strip() for l in lyrics]
    subs = pysubs2.load(str(srt_path))
    ev = sorted(subs.events, key=lambda e: e.start)
    anchors = [(e.start / 1000, e.end / 1000, k) for e, k in _anchors(song_dir, ev, seq)]
    bounds = [(0.0, 0.0)] + [(e.start / 1000, e.end / 1000) for e in ev]
    gaps = [(a[1], b[0]) for a, b in zip(bounds, bounds[1:]) if b[0] - a[1] >= min_gap]
    done = []
    for g0, g1 in gaps:
        after = next((a for a in anchors if a[0] >= g1 - 0.05), None)
        if not after:
            continue
        # 前一句取歌词里在 after 之前的；空档前面的句子都在歌词后面（Waka Waka 开头的 Anawa），就从歌词开头算
        before = max((a for a in anchors if a[1] <= g0 + 0.05 and a[2] < after[2]), key=lambda a: a[1], default=None)
        k0 = before[2] if before else -1
        missing = [k for k in range(k0 + 1, after[2]) if content(clean_parens(seq[k]))][-max_lines:]
        if not missing:
            continue
        wins = [(t, v) for t, v in cache if g0 - 0.5 <= t <= g1 - 1.0]
        first, heard = None, []
        for k in missing:   # 只补窗口里听到了关键词的句子
            keys = [w for w in re.findall(r"[\w'’]+", seq[k].lower()) if len(w) >= 4]
            hits = [t for t, v in wins if any(_phon_close(w, x) for w in keys for x in re.findall(r"[\w'’]+", (v or "").lower()))]
            if hits:
                heard.append(k)
                first = min(first, hits[0]) if first is not None else hits[0]
        missing = heard
        if not missing:
            continue
        s0, s1 = max(g0 + 0.05, first + 0.8), g1 - 0.05   # 第一个听到关键词的窗口，开口在窗口前段之后
        step = (s1 - s0) / len(missing)
        if step < 1.0:
            continue
        for n, k in enumerate(missing):
            a, b = s0 + n * step, s0 + (n + 1) * step - 0.05
            subs.events.append(pysubs2.SSAEvent(start=int(a * 1000), end=int(b * 1000), text=clean_parens(seq[k])))
            done.append({"start": round(a, 2), "end": round(b, 2), "text": clean_parens(seq[k])})
    if done:
        subs.sort()
        subs.save(str(srt_path))
    return done
