# -*- coding: utf-8 -*-
"""
新精校流程（实验中，方案见 docs/design/alignment_plan.md）：结果只写到 songs/<nn>/exp/，不动审核页上的字幕。

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


# ---------------------------------------------------------------- 2~3. 断句、文本匹配 ①


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
    from .text_match import INTERJ, _tok
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


def pick_reads(reads, plain, bin_s=8.0):
    """两遍整段识别逐段（每 bin_s 秒一段）挑一个：这一段里能在 Genius 歌词里找到的词多的那遍；一样多用第一遍。
    第一遍有时整段漏掉（Dai Dai 0:35~1:10、BZRP 3:08~4:35），有时只剩几个乱词（like the name），
    往空隙里插第二遍的词会把两遍搅成一锅（You from sound the like），所以按段整段换。"""
    from rapidfuzz import fuzz, process
    from .text_match import _tok
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


# ---------------------------------------------------------------- 4. 三个时间引擎


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


# ---------------------------------------------------------------- 主流程

