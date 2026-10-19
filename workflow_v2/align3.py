# -*- coding: utf-8 -*-
"""
新精校流程（实验中，方案见 docs/design/v2_alignment_plan.md）：结果只写到 songs/<nn>/exp/，不动审核页上的字幕。

  （不做逐句 Qwen 复核：短切片常听错，时间由三个引擎互相验证、文字由 Genius 匹配把关）
  1. 整段识别：人声在最安静处切成 ≤ 60 s 的几段，每段一次送 qwen-audio-3.1-asr-flash，拿到文字 + 字级时间戳
  2. 断句：按句末标点（. ? !）断句
  3. 文本匹配 ①：每句和 Genius 比读音 —— 像一句用 Genius 原句；像连续两句就按字级时间拆成两行；都不像保留 Qwen 文字
  4. 三个时间引擎各自给每行定时间：
       A  Qwen 字级时间戳
       B  文本匹配 ②：这行文字 ↔ 2.5 s 窗口识别（按顺序找最早听到这行开头几个词的窗口）
       C  MMS：所有行按顺序一次性强制对齐整首人声
  5. 合并：至少两个引擎开头相差 ≤ AGREE 秒算一致，用最精确的（C > A > B）；否则按规则选一个并标黄；都没有标红
  6. 漏掉的段落：有人声、但没有任何一行覆盖的地方（≥ 2 s）单独再识别一遍，列在表格里，**不补进字幕**
  7. 显示时间：统一提前 0.2 s，句末多留 0.4 s，最短 0.8 s，前后不重叠
"""

import base64
import hashlib
import json
import os
import re

import numpy as np

MODEL = "qwen-audio-3.1-asr-flash"
URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
MAX_PART = 60.0       # 一次最多识别 60 s：整首 4 分钟一次送，开头人群喊的乱码会把后面整段带偏、漏掉大段
                      # （Dai Dai 整首一次：首段主歌、Oh-eh、3:10 的西语句全没了；切成 ≤ 60 s 全都识别出来）
MATCH = 70            # 文本匹配 ①：读音相似度 >= 这个算这句 Genius
AGREE = 0.5           # 两个引擎开头相差不超过这么多秒算一致
LEAD, HOLD, MIN_SHOW = 0.2, 0.4, 0.8
MISS_MIN = 2.0        # 有人声却没字幕超过这么久，算漏掉的段落
WIN = 2.5


# ---------------------------------------------------------------- 1. 整段识别（字级时间戳）

def asr_words(y, sr, key, cache_path, t0=0.0):
    """一段人声送 qwen-audio-3.1-asr-flash，返回 [{w, s, e, punct}]（秒，已加上 t0）。按音频内容缓存。"""
    import requests
    from qwen_asr import wav_bytes
    data = wav_bytes(y)
    h = hashlib.sha1(data + MODEL.encode()).hexdigest()
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if h not in cache:
        body = {"model": MODEL,
                "input": {"messages": [{"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(data).decode()}}]}]},
                "parameters": {"format": "wav", "sample_rate": str(sr)}}
        import time
        for attempt in range(6):
            try:
                r = requests.post(URL, json=body, timeout=600, headers={
                    "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-DashScope-SSE": "disable"})
            except requests.exceptions.RequestException as e:   # 网络断了（Broken pipe 等）：等一下重试
                if attempt == 5:
                    raise RuntimeError(f"{MODEL} 网络失败：{e}")
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 200:
                break
            if "HAVE_NO_WORDS" in r.text or "NO_VALID_AUDIO" in r.text:   # 这段什么都没听出来 / 接口认为没有有效声音
                r = None
                break
            if attempt == 5:
                raise RuntimeError(f"{MODEL} 识别失败 {r.status_code}: {r.text[:200]}")
            time.sleep(3 * (attempt + 1))
        cache[h] = r.json() if r is not None else {"output": {"output": {"sentence": {"words": []}}}}
        cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    sent = cache[h]["output"]["output"]["sentence"]
    # 接口按子词给时间（Venez / ol / ana、I / ' / m）：前面带空格的是新词，不带的接在上一个词后面
    out, gap = [], False
    for w in sent.get("words", []):
        raw = w.get("text") or ""
        if not raw.strip():   # 只有空格的子词 = 词的分界（for / ␠ / a）
            gap = True
            if out:
                out[-1]["punct"] = out[-1]["punct"] or (w.get("punctuation") or "")
            continue
        # 日中韩没有空格：每个分块各算一个词（不然一整句拼成一个「词」，只剩一个起止时间，
        # 再被下面的「超过 3 s」规则把开头推到结尾前 1 s：hkt48 0:28 开唱的「心の中では…」变成 0:32.4）
        cjk = CJK.search(raw) or (out and CJK.search(out[-1]["w"][-1:]))
        new_word = not out or gap or raw.startswith(" ") or out[-1]["punct"] or cjk
        gap = False
        if new_word:
            out.append({"w": raw.strip(), "s": t0 + w["begin_time"] / 1000, "e": t0 + w["end_time"] / 1000,
                        "punct": w.get("punctuation") or ""})
        else:
            out[-1].update({"w": out[-1]["w"] + raw.strip(), "e": t0 + w["end_time"] / 1000,
                            "punct": w.get("punctuation") or ""})
    # 起点粘在上一个词结束处的异常长词（Perdón 29.9~42.2、¡Otra 0~29）：结束时间一般是对的，起点取「结束前 1 s」
    for w in out:
        if w["e"] - w["s"] > 3.0:
            w["s"] = w["e"] - 1.0
    return out


def parts(y, sr, max_len=MAX_PART, phase=0.0):
    """整首切成不超过 max_len 秒的几段，切点选在目标位置 ±15 s 内最安静的 1 s（不切在词中间）。
    phase：切点整体错开多少秒（第二遍识别用，和第一遍的切点错开）。"""
    dur = len(y) / sr
    hop = sr // 10
    k = len(y) // hop
    rms = np.convolve(np.sqrt((y[:k * hop].reshape(k, hop) ** 2).mean(1)), np.ones(10) / 10, mode="same")
    targets, t = [], (phase if phase > 0 else max_len)
    while t < dur - 15:
        targets.append(t)
        t += max_len
    if phase == 0 and dur <= max_len:
        return [(0.0, dur)]
    cuts = []
    for c in targets:
        lo, hi = max(0, int((c - 15) * 10)), min(k, int((c + 15) * 10))
        cut = (lo + int(np.argmin(rms[lo:hi]))) / 10
        if not cuts or cut - cuts[-1] > 10:
            cuts.append(cut)
    edges = [0.0] + cuts + [dur]
    # 两个目标切点挨得太近会只留一个，留下超长的块（BZRP 105~188 有 83 s）：超过 max_len 的块在中间最安静处再切一刀
    out = []
    for a, b in zip(edges, edges[1:]):
        while b - a > max_len * 1.1:
            lo, hi = int((a + 20) * 10), int((min(b - 20, a + max_len)) * 10)
            c = (lo + int(np.argmin(rms[lo:hi]))) / 10 if hi > lo else a + max_len
            out.append((a, c))
            a = c
        out.append((a, b))
    return out


def read_song(y, sr, key, cache_path, phase=0.0):
    words = []
    for p0, p1 in parts(y, sr, phase=phase):
        words += asr_words(y[int(p0 * sr):int(p1 * sr)], sr, key, cache_path, t0=p0)
    return words


# ---------------------------------------------------------------- 2~3. 断句、文本匹配 ①

def sentences(words):
    out, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.?!。？！]", w["punct"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def text_of(ws):
    """词连成文字：日中韩的词之间不加空格（心 + の中では -> 心の中では）。"""
    out = ""
    for w in ws:
        if out and not (CJK.search(out[-1]) and CJK.search(w["w"][:1])):
            out += " "
        out += w["w"]
    return out


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff10-\uff19]")


def _romaji(text):
    """日文转罗马音（そばにいるね -> soba ni iru ne），比读音用。"""
    import pykakasi
    return " ".join(x["hepburn"] for x in pykakasi.kakasi().convert(text) if x["hepburn"].strip())


@__import__("functools").lru_cache(maxsize=None)
def _key(text):
    """读音键：去掉括号里的和声、去掉语气词（Ah-ah-ah, you're lookin' for -> you're lookin' for）；日文先转罗马音。"""
    from .align2 import INTERJ, _tok
    from .gap_fill import phon
    text = re.sub(r"\([^)]*\)", " ", text)
    if CJK.search(text):
        text = _romaji(text)
    toks = [w for w in _tok(text) if w.lower() not in INTERJ] or _tok(text)
    return " ".join(phon(w) for w in toks)


def score(a, b):
    """整句读音相似度（0~100）；长短差太多（Dominicana vs I like dominicanas）直接判不像。"""
    from rapidfuzz import fuzz
    pa, pb = _key(a), _key(b)
    if not pa or not pb or not 0.6 <= len(pa) / len(pb) <= 1.7:
        return 0.0
    return float(fuzz.ratio(pa, pb))


def half(line):
    """同一段唱两遍的歌词句（Sha-Sha-Shakira, Sha-Sha-Shakira）返回前半句，否则 None。"""
    parts = [x.strip() for x in line.split(",")]
    if len(parts) % 2 == 0 and len(parts) >= 2:
        n = len(parts) // 2
        if [x.lower() for x in parts[:n]] == [x.lower() for x in parts[n:]]:
            return ", ".join(parts[:n])
    return None


def match_sentence(ws, plain, prev):
    """一句（字级）对 Genius：返回 [(字, Genius 句号或 None, 相似度, 显示文字)] —— 单句、连续两句（按词拆开）或不对。
    Genius 句是同一段唱两遍的（Sha-Sha-Shakira, Sha-Sha-Shakira），现场只唱一遍时也算，显示半句。"""
    s = text_of(ws)
    best = (0.0, None)
    for k in range(len(plain)):
        bonus = 3 if k == prev + 1 else 0   # 顺着上一句往下唱的稍微优先
        for show in [plain[k]] + ([half(plain[k])] if half(plain[k]) else []):
            sc = score(s, show) + bonus
            if sc > best[0]:
                best = (sc, [(ws, k, show)])
        if k + 1 < len(plain) and len(ws) >= 2:
            for cut in range(1, len(ws)):
                a, b = ws[:cut], ws[cut:]
                sa, sb = score(text_of(a), plain[k]), score(text_of(b), plain[k + 1])
                sc2 = (sa * len(a) + sb * len(b)) / len(ws)
                if min(sa, sb) >= 60 and sc2 >= MATCH and sc2 + bonus > best[0]:
                    best = (sc2 + bonus, [(a, k, plain[k]), (b, k + 1, plain[k + 1])])
    if best[0] >= MATCH:
        return [(part, k, round(score(text_of(part), show), 1), show) for part, k, show in best[1]]
    return [(ws, None, round(best[0], 1), None)]


def pick_reads(reads, plain, bin_s=8.0):
    """两遍整段识别逐段（每 bin_s 秒一段）挑一个：这一段里能在 Genius 歌词里找到的词多的那遍；一样多用第一遍。
    第一遍有时整段漏掉（Dai Dai 0:35~1:10、BZRP 3:08~4:35），有时只剩几个乱词（like the name），
    往空隙里插第二遍的词会把两遍搅成一锅（You from sound the like），所以按段整段换。"""
    from rapidfuzz import fuzz, process
    from .align2 import _tok
    from .gap_fill import phon
    vocab = sorted({phon(w) for l in plain for w in _tok(l) if len(w) >= 3})

    def hits(ws):
        return sum(1 for w in ws if len(w["w"]) >= 3 and process.extractOne(phon(w["w"]), vocab, scorer=fuzz.ratio, score_cutoff=80))
    end = max([w["e"] for ws in reads for w in ws] or [0.0])
    out = []
    t = 0.0
    while t < end + bin_s:
        cand = [[w for w in ws if t <= w["s"] < t + bin_s] for ws in reads]
        # Genius 词多的那遍；一样多取词多的；再一样取前面那遍
        out += max(enumerate(cand), key=lambda x: (hits(x[1]), len(x[1]) > 0, -x[0]))[1]
        t += bin_s
    return sorted(out, key=lambda w: w["s"])


def confirm_live(rows, words2, pad=1.5, need=60):
    """Genius 里没有的句子（现场改词 / 即兴 / 喊话）：第二遍整段识别（切点和第一遍错开 30 s，同样是长段落）
    在同一位置（± pad 秒）也听到这句才算数；否则只在表格里列出来、不进字幕。
    不用「切一小段再听」：几秒的短片段换哪个模型都会听错（Ecuatoriana -> venezolana / Porto Alegre）。"""
    from rapidfuzz import fuzz
    for r in rows:
        if r["genius"]:
            continue
        toks = [w for w in re.findall(r"[^\W\d_]+", _romaji(r["heard"]) if CJK.search(r["heard"]) else r["heard"])]
        if not (sum(1 for w in toks if len(w) >= 3) >= 2 or any(len(w) >= 5 for w in toks)):
            # 太短、不像词（开场人群喊元音：If apa / If ini / I / A），两遍都听成一样的乱码也不算
            r["other"], r["confirm"], r["unconfirmed"] = "（太短、不像词）", 0.0, True
            continue
        other = text_of([w for w in words2 if r["A"] - pad <= w["s"] <= r["A_end"] + pad])
        sc = fuzz.partial_ratio(_key(r["heard"]), _key(other)) if _key(r["heard"]) and _key(other) else 0
        r["other"], r["confirm"] = other, round(sc, 1)
        if sc < need:
            r["unconfirmed"] = True


def lead_interjections(rows, per_syllable=0.35):
    """Genius 句开头的语气词（Ah-ah-ah, you're lookin' for）是拖腔，ASR 听不出来，这句的开头就落在第一个听出来的词上，
    晚了约 1 s。开头往前补「每个音节约 0.35 s」，但不早于上一行结束（这几个音就唱在两句中间）。"""
    from .align2 import INTERJ, _tok
    for i, r in enumerate(rows):
        if not r["genius"]:
            continue
        lead = []
        for w in re.split(r"[\s,]+", re.sub(r"\([^)]*\)", " ", r["text"]).strip()):
            parts = [x for x in w.lower().split("-") if x]
            if parts and all(x in INTERJ for x in parts):
                lead += parts
            else:
                break
        heard = {w.lower() for w in _tok(r["heard"])}
        n = sum(1 for x in lead if x not in heard)
        if not n:
            continue
        prev_end = rows[i - 1]["A_end"] if i else 0.0
        new = max(prev_end + 0.05, r["A"] - per_syllable * n)
        if new < r["A"] - 0.1:
            r["A_raw"], r["A"] = r["A"], round(new, 2)
            r["lead_note"] = f"句首「{' '.join(lead)}」ASR 没听出来，开头往前补 {r['A_raw'] - r['A']:.1f}s"


PAUSE = 0.4           # 词之间停顿超过这么久，也算一个短语的边界


def phrases(ws, max_words=6):
    """按逗号 / 句号 / 停顿切成短语（识别结果常把一整段连成一句：Venezolana, ecuatoriana, …, colombiana.）。
    超过 max_words 个词、中间既没标点也没停顿的长串（某一遍识别整段没有标点：sarà perché ti amo cade una stella …
    che te ne frega …，跨了三句歌词）拆成一个词一段，让后面的动态规划在任意词之间找切点。
    每个词记下原来属于哪个短语（pid），对不上歌词的相邻小段再按 pid 拼回去。"""
    out, cur = [], []
    for i, w in enumerate(ws):
        cur.append(w)
        nxt = ws[i + 1] if i + 1 < len(ws) else None
        if nxt is None or re.search(r"[,，.?!。？！]", w["punct"]) or nxt["s"] - w["e"] >= PAUSE:
            out.append(cur)
            cur = []
    units = []
    for pid, p in enumerate(out):
        for w in p:
            w["pid"] = pid
        units += [[w] for w in p] if len(p) > max_words else [p]
    return units


def match_phrases(ws, plain, prev, max_group=16, gap=1.5, max_line=8):
    """整首的短语怎么拼成字幕行：动态规划找总分最高的切法。
    一组短语（中间停顿不超过 gap 秒、最多 max_group 个）对上一句 Genius（或一句唱了两句歌词）得分 =（相似度 − 60）× 词数；
    哪句都对不上的短语单独成一行，得 0 分。多拼进来不相干的短语会拉低相似度、反而扣分，所以不会乱拼。"""
    ph = phrases(ws)
    n = len(ph)
    best = [0.0] + [-1e9] * n
    back = [None] * (n + 1)
    memo = {}
    for i in range(1, n + 1):
        # 第 i 个短语单独成行（不对 Genius）
        best[i], back[i] = best[i - 1], (i - 1, None)
        for j in range(i - 1, max(-1, i - 1 - max_group), -1):
            if j < i - 1 and ph[j + 1][0]["s"] - ph[j][-1]["e"] > gap:
                break
            group = [w for p in ph[j:i] for w in p]
            if (j, i) not in memo:
                memo[(j, i)] = match_sentence(group, plain, -1)
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
    # 对不上歌词、原来在同一个短语里的相邻小段拼回一行（不然会出一个词一行的字幕）
    merged = []
    for part, k, sc, show in out:
        if merged and k is None and merged[-1][1] is None and merged[-1][0][-1].get("pid") == part[0].get("pid") \
                and len(merged[-1][0]) + len(part) <= max_line:   # 一行最多 max_line 个词，不出一整屏的长字幕
            merged[-1] = (merged[-1][0] + part, None, max(merged[-1][2], sc), None)
        else:
            merged.append((part, k, sc, show))
    return merged


# ---------------------------------------------------------------- 4. 三个时间引擎

def engine_b(rows, windows):
    """文本匹配 ②：每行开头几个实词，按顺序找最早听到它们的一串窗口；开头 = 这串窗口估出来的开口时间。"""
    from .align2 import _tok
    from .gap_fill import _phon_close
    for r in rows:
        toks = [w for w in _tok(re.sub(r"\([^)]*\)", " ", r["text"])) if len(w) >= 3] or _tok(r["text"])
        head = toks[:2]
        r["B"] = None
        if not head:
            continue
        # 每行只在自己附近（Qwen 给的位置前后 6 s）找，找错了也不会带偏后面的行
        hits = [t for t, v in windows if r["A"] - 6 <= t <= r["A"] + 6 and
                all(any(_phon_close(h, x) or h.lower() == x.lower() for x in _tok(v or "")) for h in head)]
        if not hits:
            continue
        clusters = [[hits[0]]]
        for t in hits[1:]:
            (clusters[-1].append(t) if t - clusters[-1][-1] <= 1.0 else clusters.append([t]))
        hd = 0.3 * len(head)

        def est(c):
            first, last = c[0], c[-1]
            return (last + max(first, first + WIN - hd - 0.3)) / 2 if last > first else first + 0.5
        r["B"] = round(min((est(c) for c in clusters), key=lambda x: abs(x - r["A"])), 2)


def engine_c(rows, y, sr, lang, pad=2.0):
    """MMS：每行在「Qwen 给的位置 ± pad 秒、且不越过前后行」里强制对齐，取首词起点 / 末词终点。
    （整首一次性对齐时，开头 37 s 没唱歌的人声会把前几行拉到最前面去。）"""
    from refine_timing import emission_full, load_model, romanize
    model, tokenizer, aligner = load_model()
    em, fr = emission_full(model, y)
    dur = len(y) / sr
    for i, r in enumerate(rows):
        r["C"] = r["C_end"] = r["C_score"] = None
        toks = romanize(r["text"], lang)
        if not toks:
            continue
        lo = max(rows[i - 1]["A_end"] - 0.3 if i else 0.0, r["A"] - pad)
        hi = min(rows[i + 1]["A"] + 0.3 if i + 1 < len(rows) else dur, r["A_end"] + pad)
        if hi - lo < 0.5:
            continue
        a0, a1 = int(lo * fr), int(hi * fr)
        try:
            spans = [sp for sp in aligner(em[a0:a1], tokenizer(["*"] + toks + ["*"]))[1:-1] if sp]
        except Exception:  # noqa: BLE001
            continue
        if spans:
            r["C"] = round(lo + spans[0][0].start / fr, 2)
            r["C_end"] = round(lo + spans[-1][-1].end / fr, 2)
            r["C_score"] = round(float(np.mean([x.score for sp in spans for x in sp])), 3)


def merge(rows):
    """至少两个引擎开头相差 ≤ AGREE：一致，用最精确的（C > A > B）；只有一个引擎：用它、标黄；
    几个都有但对不上：用 A（Qwen 字级时间戳，实测和已知点差 ≤ 0.2 s）、标黄；都没有：标红。"""
    for r in rows:
        got = {k: r.get(k) for k in ("A", "B", "C") if r.get(k) is not None}
        agree = [(a, b) for a in got for b in got if a < b and abs(got[a] - got[b]) <= AGREE]
        if agree:
            pick = next(k for k in ("C", "A", "B") if any(k in p for p in agree))
            r["verdict"], r["note"] = "ok", "、".join(sorted({x for p in agree for x in p})) + " 一致"
        elif len(got) == 1:
            pick = next(iter(got))
            r["verdict"], r["note"] = "warn", f"只有 {pick} 有结果"
        elif got:
            pick = "A" if "A" in got else "B"
            spread = max(got.values()) - min(got.values())
            r["verdict"], r["note"] = "warn", f"引擎不一致（相差 {spread:.1f}s），用 {pick}"
        else:
            r["verdict"], r["note"], pick = "bad", "三个引擎都找不到位置", None
        r["pick"] = pick
        if pick:
            r["s"] = got[pick]
            r["e"] = {"A": r.get("A_end"), "C": r.get("C_end"), "B": None}[pick] or r.get("A_end") or (r["s"] + 1.5)


# ---------------------------------------------------------------- 6. 漏掉的段落

def missed(rows, y, sr, words2, plain):
    """有人声、但没有任何一行字幕的地方：列出第二遍识别在这里听到了什么（不补进字幕）。"""
    from .gap_fill import voiced_ratio
    dur = len(y) / sr
    spans = sorted((r["s"], r["e"]) for r in rows if r.get("s") is not None)
    bounds = [(0.0, 0.0)] + spans + [(dur, dur)]
    out = []
    for (_, g0), (g1, _) in zip(bounds, bounds[1:]):
        if g1 - g0 < MISS_MIN or voiced_ratio(y, sr, g0, g1) < 0.4:
            continue
        heard = text_of([w for w in words2 if g0 - 0.3 <= w["s"] < g1])
        if not heard:
            continue
        best = max(((score(heard, p), p) for p in plain), default=(0.0, ""))
        out.append({"s": round(g0, 2), "e": round(g1, 2), "heard": heard,
                    "genius": best[1] if best[0] >= 50 else "", "score": round(best[0], 1)})
    return out


# ---------------------------------------------------------------- 主流程

def run(song_dir, lang, lyrics, out_dir):
    import librosa
    import llm
    import pysubs2
    from qwen_asr import SR
    from .gap_fill import clean_parens

    d = song_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    llm.load_env()
    key = os.environ["ALIYUN_BAILIAN_API_KEY"]
    cache = d / "reports" / "asr31_cache.json"
    y, _ = librosa.load(str(d / "vocals.wav"), sr=SR, mono=True)
    lines = [l.strip() for l in lyrics if l.strip()]
    plain = [clean_parens(l) for l in lines]

    words1 = read_song(y, SR, key, cache)                      # 第一遍：切点在 60、120… 附近最安静处
    words2 = read_song(y, SR, key, cache, phase=MAX_PART / 2)  # 第二遍：切点错开 30 s
    words3 = read_song(y, SR, key, cache, phase=MAX_PART / 4)  # 第三遍：切点错开 15 s
    for ws, k in ((words1, 1), (words2, 2), (words3, 3)):
        for w in ws:
            w["src"] = k
    words = pick_reads([words1, words2, words3], plain)
    (out_dir / "asr_words.json").write_text(json.dumps(words, ensure_ascii=False, indent=0))
    (out_dir / "asr_words_2.json").write_text(json.dumps(words2, ensure_ascii=False, indent=0))
    (out_dir / "asr_words_3.json").write_text(json.dumps(words3, ensure_ascii=False, indent=0))

    rows, prev = [], -1
    # 句号也只是短语边界：整首的短语按顺序拼起来对 Genius（模型会在一句歌词中间点句号：aquí no vuelvo. / No quiero…）
    for ws in [words]:
        for part, k, sc, show in match_phrases(ws, plain, prev):
            if k is not None:
                prev = k
            heard = text_of(part)
            src = max((1, 2, 3), key=lambda k: sum(1 for w in part if w.get("src") == k))
            rows.append({"src": src, "heard": heard, "genius": lines[k] if k is not None else "", "score": sc,
                         "text": show if k is not None else re.sub(r"[.?!,]+$", "", heard[0].upper() + heard[1:]),
                         "A": round(part[0]["s"], 2), "A_end": round(part[-1]["e"], 2)})

    lead_interjections(rows)
    reads = {1: words1, 2: words2, 3: words3}
    for k in (1, 2, 3):   # 不在 Genius 里的句子：另外两遍里有一遍也听到才算数
        confirm_live([r for r in rows if r["src"] == k], [w for j, ws in reads.items() if j != k for w in ws])
    cache_f = d / "reports" / "dense_cache.json"
    windows = sorted((float(k), v) for k, v in json.loads(cache_f.read_text()).items()) if cache_f.exists() else []
    engine_b(rows, windows)
    engine_c(rows, y, SR, lang)
    merge(rows)
    shown = sorted([r for r in rows if r.get("s") is not None and not r.get("unconfirmed")], key=lambda r: r["s"])
    for i, r in enumerate(shown):
        nxt = shown[i + 1]["s"] if i + 1 < len(shown) else r["e"] + 5
        r["show_e"] = min(max(r["e"] + HOLD, r["s"] + MIN_SHOW), nxt - 0.05)
    prev_e = 0.0
    for r in shown:
        r["show_s"] = max(prev_e + 0.05, r["s"] - LEAD, 0.0)
        r["show_e"] = max(r["show_e"], r["show_s"] + 0.3)
        prev_e = r["show_e"]
    gaps = missed(shown, y, SR, words2, plain)

    subs = pysubs2.SSAFile()
    for r in shown:
        subs.events.append(pysubs2.SSAEvent(start=int(r["show_s"] * 1000), end=int(r["show_e"] * 1000), text=r["text"]))
    subs.save(str(out_dir / "lyrics.srt"))
    table = []
    for r in rows:
        if r.get("unconfirmed"):
            table.append({"start_ms": round(r["A"] * 1000), "end_ms": round(r["A_end"] * 1000), "genius": "", "qwen": r["heard"],
                          "text": "", "heard": "", "A": r.get("A"), "B": r.get("B"), "C": r.get("C"), "C_score": r.get("C_score"),
                          "pick": None, "verdict": "unconfirmed", "removed": True, "suspect": None,
                          "strategy": f"Genius 里没有，另外两遍整段识别在这里听到的是「{r.get('other', '')}」，"
                                      f"对不上（{r.get('confirm', 0):.0f} 分），没放进字幕"})
            continue
        src = (f"这一段用第{'一二三'[r['src'] - 1]}遍识别（Genius 词最多） → " if r["src"] != 1 else "") + (f"对上 Genius（读音 {r['score']:.0f} 分）" if r["genius"] else \
            f"Genius 里没有（最像 {r['score']:.0f} 分），用 ASR 文字；另外两遍整段识别也听到（{r.get('confirm', 0):.0f} 分）")
        table.append({"start_ms": round(r["show_s"] * 1000) if r.get("show_s") is not None else None,
                      "end_ms": round(r["show_e"] * 1000) if r.get("show_e") is not None else None,
                      "genius": r["genius"], "qwen": r["heard"], "text": r["text"], "heard": "",
                      "A": r.get("A"), "B": r.get("B"), "C": r.get("C"), "C_score": r.get("C_score"),
                      "pick": r.get("pick"), "verdict": r["verdict"],
                      "strategy": f"整段识别 → {src} → 时间：{r['note']}" + (f"，用 {r['pick']}" if r.get("pick") else "")
                                  + (f"；{r['lead_note']}" if r.get("lead_note") else ""),
                      "removed": r.get("s") is None, "suspect": None})
    for g in gaps:
        table.append({"start_ms": round(g["s"] * 1000), "end_ms": round(g["e"] * 1000), "genius": g["genius"],
                      "qwen": g["heard"], "text": "", "heard": "", "A": None, "B": None, "C": None, "C_score": None,
                      "pick": None, "verdict": "miss", "removed": True, "suspect": None,
                      "strategy": f"漏掉的段落：有人声没字幕（{g['e'] - g['s']:.1f}s），第二遍整段识别在这里听到的列在这里，没有补进字幕"
                                  + (f"；最像 Genius「{g['genius']}」{g['score']:.0f} 分" if g["genius"] else "")})
    table.sort(key=lambda r: (r["start_ms"] is None, r["start_ms"] or 0))
    (out_dir / "lines.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    return rows, gaps


def run_exp(slug, name):
    """跑一首的实验：对齐 → 翻译，全部写到 songs/<nn>/exp/。"""
    import subprocess
    import acoustic
    from .paths import ROOT, VENV_PY, Concert, read_json
    from .refine import sub_title
    c = Concert(slug)
    it = c.item(name)
    d = c.song_dir(it)
    out = d / "exp"
    info = read_json(d / "song.json", {})
    lang = "auto" if len(info.get("langs") or []) > 1 else info.get("lang", "en")
    os.environ["QWEN_CACHE"] = str(d / "reports" / "qwen_cache.json")
    rows, gaps = run(d, lang, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")], out)
    # 不再做逐句 Qwen 复核：1~2 s 的短切片常听错（Ecuatoriana -> I thought I had），时间由三个引擎互相验证、
    # 文字由 Genius 匹配把关，复核没有增加信息
    srt = out / "lyrics.srt"
    table = json.loads((out / "lines.json").read_text())
    subprocess.run([str(VENV_PY), str(ROOT / "workflow" / "translate_ass.py"), str(srt), "-o", str(out / "lyrics.ass"),
                    "--cache", str(d / "zh_cache.json"), "--title", sub_title(c, it), "--style", "bzrp"],
                   check=True, stdout=subprocess.DEVNULL)
    ok = sum(1 for r in table if r["verdict"] == "ok")
    warn = sum(1 for r in table if r["verdict"] == "warn")
    bad = sum(1 for r in table if r["verdict"] == "bad")
    print(f"{it['title']}: {len(table) - len(gaps)} 行（一致 {ok}，标黄 {warn}，标红 {bad}），漏掉的段落 {len(gaps)} 处 -> {out}")


def run_post(name, lang, covers=True):
    """v1 单曲（posts/<name>/）跑新流程：字幕 -> exp/lyrics.srt / lyrics.ass，新样式封面 -> exp/covers/，
    原来的字幕和封面（lyrics.ass、post/cover/）不动。"""
    import subprocess
    import sys
    from .paths import ROOT, VENV_PY
    d = ROOT / "posts" / name
    out = d / "exp"
    (d / "reports").mkdir(exist_ok=True)
    post = json.loads((d / "post" / f"{name}.json").read_text())
    song = post.get("song") or {}
    title, artist = song.get("title") or name, song.get("artist") or ""
    lyrics = [l.strip() for l in (d / "lyrics.txt").read_text().splitlines() if l.strip() and not l.startswith("[")]
    run(d, lang, lyrics, out)
    subprocess.run([str(VENV_PY), str(ROOT / "workflow" / "translate_ass.py"), str(out / "lyrics.srt"), "-o", str(out / "lyrics.ass"),
                    "--cache", str(d / "zh_cache.json"), "--title", f"《{title}》 {artist}".strip(), "--style", "bzrp"],
                   check=True, stdout=subprocess.DEVNULL)
    table = json.loads((out / "lines.json").read_text())
    print(f"{name}: {sum(1 for r in table if not r['removed'])} 行（一致 {sum(1 for r in table if r['verdict'] == 'ok')}，"
          f"标黄 {sum(1 for r in table if r['verdict'] == 'warn')}，未确认 {sum(1 for r in table if r['verdict'] == 'unconfirmed')}）", flush=True)
    if not covers:
        return
    sys.path.insert(0, str(ROOT / "workflow"))
    import make_meta
    zh = song.get("artist_zh") or ""
    who = f"{zh} {artist}" if zh and zh != artist else artist
    sub = f"{who} · {make_meta.subs_tag(post.get('subtitles') or [])}".strip(" ·")
    from .package import PER_SHOT, TEXT_LIFT, CLOSEUP_MIN
    log = out / "covers.log"
    with log.open("w") as fh:
        r = subprocess.run([str(VENV_PY), str(ROOT / "workflow" / "make_cover.py"), "--name", name, "--title", title,
                            "--subtitle", sub, "--video", str(d / "source.mp4"), "--out-dir", str(out / "covers"),
                            "--sub-fit", "natural", "--per-shot", PER_SHOT, "--text-lift", str(TEXT_LIFT),
                            "--closeup-min", str(CLOSEUP_MIN)], stdout=fh, stderr=subprocess.STDOUT)
    n = len(list((out / "covers").glob("*_[0-9][0-9].jpg"))) if (out / "covers").exists() else 0
    print(f"{name}: 封面 {n} 张" + ("" if r.returncode == 0 else f"（失败，见 {log}）"), flush=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "workflow"))
    run_exp(sys.argv[1], sys.argv[2])
