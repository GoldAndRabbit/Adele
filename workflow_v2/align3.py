# -*- coding: utf-8 -*-
"""
新精校流程（实验中，方案见 docs/design/v2_alignment_plan.md）：结果只写到 songs/<nn>/exp/，不动审核页上的字幕。

  1. 整段识别：整首人声一次送 qwen-audio-3.1-asr-flash（> 5 分钟在最安静处切段），拿到文字 + 字级时间戳
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
MAX_PART = 280.0      # 接口上限 5 分钟，留余量
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
        for attempt in range(4):
            r = requests.post(URL, json=body, timeout=600, headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-DashScope-SSE": "disable"})
            if r.status_code == 200:
                break
            if "HAVE_NO_WORDS" in r.text:   # 这段什么都没听出来
                r = None
                break
            if attempt == 3:
                raise RuntimeError(f"{MODEL} 识别失败 {r.status_code}: {r.text[:200]}")
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
        new_word = not out or gap or raw.startswith(" ") or out[-1]["punct"]
        gap = False
        if new_word:
            out.append({"w": raw.strip(), "s": t0 + w["begin_time"] / 1000, "e": t0 + w["end_time"] / 1000,
                        "punct": w.get("punctuation") or ""})
        else:
            out[-1].update({"w": out[-1]["w"] + raw.strip(), "e": t0 + w["end_time"] / 1000,
                            "punct": w.get("punctuation") or ""})
    return out


def parts(y, sr, max_len=MAX_PART):
    """整首超过 max_len 秒：在最安静的 1 s 切开（不切在词中间）。"""
    dur = len(y) / sr
    n = int(np.ceil(dur / max_len))
    if n <= 1:
        return [(0.0, dur)]
    hop = sr // 10
    k = len(y) // hop
    rms = np.convolve(np.sqrt((y[:k * hop].reshape(k, hop) ** 2).mean(1)), np.ones(10) / 10, mode="same")
    cuts = []
    for i in range(1, n):
        c = int(dur * i / n * 10)
        lo, hi = max(0, c - 200), min(k, c + 200)
        cuts.append((lo + int(np.argmin(rms[lo:hi]))) / 10)
    edges = [0.0] + cuts + [dur]
    return list(zip(edges, edges[1:]))


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
    return " ".join(w["w"] for w in ws)


def _key(text):
    """读音键：去掉括号里的和声、去掉语气词（Ah-ah-ah, you're lookin' for -> you're lookin' for）。"""
    from .align2 import INTERJ, _tok
    from .gap_fill import phon
    text = re.sub(r"\([^)]*\)", " ", text)
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

def missed(rows, y, sr, key, cache_path, plain):
    """有人声、但没有任何一行覆盖的地方，单独再识别一遍；列出来，不补进字幕。"""
    import llm
    from openai import OpenAI
    from qwen_asr import ENDPOINT, transcribe
    from .gap_fill import voiced_ratio
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    dur = len(y) / sr
    spans = sorted((r["s"], r["e"]) for r in rows if r.get("s") is not None)
    bounds = [(0.0, 0.0)] + spans + [(dur, dur)]
    out = []
    for (_, g0), (g1, _) in zip(bounds, bounds[1:]):
        if g1 - g0 < MISS_MIN or voiced_ratio(y, sr, g0, g1) < 0.4:
            continue
        seg = y[int(g0 * sr):int(g1 * sr)]
        text = text_of(asr_words(seg, sr, key, cache_path, t0=g0))
        # 新模型在这种地方常常什么都不出（Sha-Sha-Shakira），再用 qwen3-asr-flash 听一遍
        old = transcribe(client, seg, "auto") or ""
        from .gap_fill import NON_LATIN
        if not re.search(r"[A-Za-zÀ-ÿ]", old) and NON_LATIN.search(old):
            old = ""   # 外语歌里只听出一个中文字（你。）：拖长音尾巴上的幻听，当没听出来
        if not text and not old:
            continue
        heard = " / ".join(x for x in (text and f"新模型：{text}", old and f"qwen3：{old}") if x) or "（两个模型都没听出来）"
        best = max(((score(text or old, p), p) for p in plain), default=(0.0, ""))
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

    words = []
    for p0, p1 in parts(y, SR):
        words += asr_words(y[int(p0 * SR):int(p1 * SR)], SR, key, cache, t0=p0)
    (out_dir / "asr_words.json").write_text(json.dumps(words, ensure_ascii=False, indent=0))

    rows, prev = [], -1
    for ws in sentences(words):
        for part, k, sc, show in match_sentence(ws, plain, prev):
            if k is not None:
                prev = k
            heard = text_of(part)
            rows.append({"heard": heard, "genius": lines[k] if k is not None else "", "score": sc,
                         "text": show if k is not None else re.sub(r"[.?!,]+$", "", heard[0].upper() + heard[1:]),
                         "A": round(part[0]["s"], 2), "A_end": round(part[-1]["e"], 2)})

    cache_f = d / "reports" / "dense_cache.json"
    windows = sorted((float(k), v) for k, v in json.loads(cache_f.read_text()).items()) if cache_f.exists() else []
    engine_b(rows, windows)
    engine_c(rows, y, SR, lang)
    merge(rows)
    shown = sorted([r for r in rows if r.get("s") is not None], key=lambda r: r["s"])
    for i, r in enumerate(shown):
        nxt = shown[i + 1]["s"] if i + 1 < len(shown) else r["e"] + 5
        r["show_e"] = min(max(r["e"] + HOLD, r["s"] + MIN_SHOW), nxt - 0.05)
    prev_e = 0.0
    for r in shown:
        r["show_s"] = max(prev_e + 0.05, r["s"] - LEAD, 0.0)
        r["show_e"] = max(r["show_e"], r["show_s"] + 0.3)
        prev_e = r["show_e"]
    gaps = missed(shown, y, SR, key, cache, plain)

    subs = pysubs2.SSAFile()
    for r in shown:
        subs.events.append(pysubs2.SSAEvent(start=int(r["show_s"] * 1000), end=int(r["show_e"] * 1000), text=r["text"]))
    subs.save(str(out_dir / "lyrics.srt"))
    table = []
    for r in rows:
        src = f"对上 Genius（读音 {r['score']:.0f} 分）" if r["genius"] else f"Genius 里没有（最像 {r['score']:.0f} 分），用 Qwen 文字"
        table.append({"start_ms": round(r["show_s"] * 1000) if r.get("show_s") is not None else None,
                      "end_ms": round(r["show_e"] * 1000) if r.get("show_e") is not None else None,
                      "genius": r["genius"], "qwen": r["heard"], "text": r["text"], "heard": "",
                      "A": r.get("A"), "B": r.get("B"), "C": r.get("C"), "C_score": r.get("C_score"),
                      "pick": r.get("pick"), "verdict": r["verdict"],
                      "strategy": f"整段识别 → {src} → 时间：{r['note']}" + (f"，用 {r['pick']}" if r.get("pick") else ""),
                      "removed": r.get("s") is None, "suspect": None})
    for g in gaps:
        table.append({"start_ms": round(g["s"] * 1000), "end_ms": round(g["e"] * 1000), "genius": g["genius"],
                      "qwen": g["heard"], "text": "", "heard": "", "A": None, "B": None, "C": None, "C_score": None,
                      "pick": None, "verdict": "miss", "removed": True, "suspect": None,
                      "strategy": f"漏掉的段落：有人声没字幕（{g['e'] - g['s']:.1f}s），单独再听一遍的结果列在这里，没有补进字幕"
                                  + (f"；最像 Genius「{g['genius']}」{g['score']:.0f} 分" if g["genius"] else "")})
    table.sort(key=lambda r: (r["start_ms"] is None, r["start_ms"] or 0))
    (out_dir / "lines.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    return rows, gaps


def run_exp(slug, name):
    """跑一首的实验：对齐 → 逐句 Qwen 复核（只出报告）→ 翻译，全部写到 songs/<nn>/exp/。"""
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
    srt = out / "lyrics.srt"
    rep = out / "verify_report.json"
    subprocess.run([str(VENV_PY), str(ROOT / "workflow" / "verify_qwen.py"), str(srt), "--ref", str(d / "lyrics.txt"),
                    "--vocals", str(d / "vocals.wav"), "--lang", lang, "--no-swap", "--hide-below", "0",
                    "-o", str(out / "verify_out.srt"), "--report", str(rep)], check=True, stdout=subprocess.DEVNULL)
    (out / "verify_out.srt").unlink(missing_ok=True)
    verify = json.loads(rep.read_text())
    table = json.loads((out / "lines.json").read_text())
    vl = verify.get("lines", [])
    sus = verify.get("suspect", [])
    for r in table:
        if r["start_ms"] is None or not r["text"]:
            continue
        t = r["start_ms"] / 1000
        m = min(vl, key=lambda v: abs(v["start"] - t), default=None)
        if m and abs(m["start"] - t) < 0.3:
            r["heard"] = m.get("heard") or ""
        s = next((x for x in sus if abs(x["start"] - t) < 0.3), None)
        r["suspect"] = s["score"] if s else None
    (out / "lines.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    subprocess.run([str(VENV_PY), str(ROOT / "workflow" / "translate_ass.py"), str(srt), "-o", str(out / "lyrics.ass"),
                    "--cache", str(d / "zh_cache.json"), "--title", sub_title(c, it), "--style", "bzrp"],
                   check=True, stdout=subprocess.DEVNULL)
    ok = sum(1 for r in table if r["verdict"] == "ok")
    warn = sum(1 for r in table if r["verdict"] == "warn")
    bad = sum(1 for r in table if r["verdict"] == "bad")
    print(f"{it['title']}: {len(table) - len(gaps)} 行（一致 {ok}，标黄 {warn}，标红 {bad}），漏掉的段落 {len(gaps)} 处 -> {out}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "workflow"))
    run_exp(sys.argv[1], sys.argv[2])
