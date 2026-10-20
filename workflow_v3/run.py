# -*- coding: utf-8 -*-
"""v3 主流程：听 → 整首顺序对齐 → 锚点 → 锚点之间重新识别、再对齐（最多 3 轮）→ 歌词外 → 时间 → 显示 → 翻译。

    .venv/bin/python -m workflow_v3.run song shakira_madrid_2026 37_bzrp_music_sessions_53
    .venv/bin/python -m workflow_v3.run post lose_yourself_2009
"""

import json
import os
import re
from collections import Counter

import numpy as np

from workflow_v2 import align4 as V2
from workflow_v2.align4 import LATIN, units, tidy
from . import listen as L
from .align import CJK, Lyrics, run_alignment, tokens

ROUNDS = 3        # 锚点之间重新识别、再对齐最多几轮
AGREE = 0.5       # 几个时间来源相差不超过这么多算一致
LEAD, HOLD, MIN_SHOW = 0.2, 0.4, 0.8
TALK_STEADY = 0.6  # 歌词范围里的歌词外段落：音高稳定度低于这个算在说话
TALK_STEADY_OUT = 0.8  # 歌词范围之外（开场 / 结尾）：门槛放宽
BLOCK_GAP = 6.0   # 开头 / 结尾单独一块：和后面隔着这么久没字幕
BLOCK_TALK = 0.5  # 这一块（含对上 Genius 的行）整块稳定度低于这个：是对话
SPLIT_PAUSE = 1.5  # 一行中间停顿超过这么久，显示时拆成两行
LONG = 12         # 一行超过这么多词，在最靠中间的逗号处拆
SHOW_MIN = 0.4    # 不是锚点、不在顺序中间的行，至少对上这么多才显示
TALK_WORDS = 5    # 歌词外段落至少这么多词（日中韩按字，翻倍）才可能是讲话（说唱中间的碎词不算）


# ---------------------------------------------------------------- 第 3 步：锚点之间逐段校准

def intervals(occ, ly, dur, cells):
    """需要重新识别的区间：两个锚点之间，Genius 里应该有句子、但这里唱到的行覆盖不够（或几乎没听到东西）。
    返回 [(起, 止, 应该唱的行号)]。"""
    anchors = [o for o in occ if o["anchor"]]
    out = []
    bounds = [None] + anchors + [None]
    for a, b in zip(bounds, bounds[1:]):
        t0 = a["e"] if a else 0.0
        t1 = b["s"] if b else dur
        if t1 - t0 < 2.0:
            continue
        if a and b and b["k"] > a["k"]:
            want = list(range(a["k"] + 1, b["k"]))
        elif a and (not b or b["k"] <= a["k"]):
            want = [a["k"] + 1] if a["k"] + 1 < len(ly.lines) else []
        elif b:
            want = [b["k"] - 1] if b["k"] > 0 else []
        else:
            want = []
        want = [k for k in want if ly.key[k]]
        inside = [o for o in occ if not o["anchor"] and t0 - 0.2 <= o["s"] < t1]
        heard = sum(1 for c in cells if t0 <= c["s"] < t1)
        covered = sum(o["coverage"] for o in inside if o["k"] in want)
        if want and (covered < 0.6 * len(want) or heard < 2 * len(want)):
            out.append((t0, t1, want))
    return out


def calibrate(y, sr, key, cache, cands, reads, ly, occ, cells, dur, rnd):
    """每个需要的区间重新识别一次（在两端的自然停顿处切、多试几个起止，挑和该唱的句子最像的），作为新的一遍加进去。"""
    from rapidfuzz import fuzz
    added = []
    for t0, t1, want in intervals(occ, ly, dur, cells):
        target = " ".join(t[0] for k in want for t in ly.tok[ly.start[k]:ly.end[k]])

        def judge(ws):
            ks = " ".join(t[0] for w in ws for t in tokens(w["w"]))
            return len(ks) * fuzz.partial_ratio(ks, target) / 100 if len(ks) >= 4 else 0.0
        ws = L.relisten(y, sr, key, cache, cands, t0, t1, judge, src=100 * rnd + len(added) + 1)
        if ws:
            added.append(ws)
    return added


# ---------------------------------------------------------------- 时间

def vote(src):
    """几个时间来源（各遍识别 + MMS），相差 ≤ AGREE 的算一伙，取人数最多的一伙。返回 (时间, 判定, 说明, 一致的来源)。"""
    src = {k: v for k, v in src.items() if v is not None}
    if not src:
        return None, "bad", "没有时间来源", []
    items = sorted(src.items(), key=lambda x: x[1])
    best = None
    for i in range(len(items)):
        grp = [x for x in items if items[i][1] <= x[1] <= items[i][1] + AGREE]
        k = (len(grp), any(n == "C" for n, _ in grp))
        if best is None or k > best[0]:
            best = (k, grp)
    grp = best[1]
    names = [n for n, _ in grp]
    if len(grp) >= 2:
        t = dict(grp)["C"] if "C" in names else float(np.median([v for n, v in grp]))
        return t, "ok", f"{'、'.join(names)} 一致", names
    if len(items) == 1:
        return items[0][1], "ok", f"只有 {items[0][0]}", names
    return float(np.median([v for _, v in items])), "warn", "各来源不一致（" + "，".join(f"{n} {v:.1f}" for n, v in items) + "）", []


# ---------------------------------------------------------------- 显示：一行太长 / 中间停顿太久就拆

def display_rows(o, ly, cells, next_s=None):
    """一次唱到的行 -> 一条或几条显示行 [(起止时间来源的 cell 下标们, 显示文字)]。
    覆盖 ≥ 0.6：显示整句 Genius；否则只显示对上的那一截（现场只唱了半句）。中间停顿 > SPLIT_PAUSE、超过 LONG 词时拆开。"""
    k = o["k"]
    line = ly.lines[k]
    toks = ly.tok
    if o.get("filled"):
        from workflow_v2.gap_fill import clean_parens
        return [(o["cells"], tidy(clean_parens(line) or line))]
    if o.get("live_change"):   # 现场改词：显示听到的原话
        h = o["heard"]
        return [(o["cells"], h[:1].upper() + h[1:])]
    pairs = list(zip(o["cells"], o["toks"]))
    # 只显示对上的那一截（现场只唱了半句），还是整句：看后面没对上的词来不来得及唱（每词约 0.3 s）。
    # 来得及（下一句还没开始）就是唱了但没听出来（观众合唱、结尾），显示整句；来不及才是真的只唱了半句
    rest = [t for t in range(max(o["toks"]) + 1, ly.end[k]) if not ly.opt[t]]
    room = (next_s if next_s is not None else 1e9) - cells[o["cells"][-1]]["e"]
    if o["coverage"] >= 0.6 or o.get("seq") or room >= 0.3 * len(rest):
        lo_t, hi_t = ly.start[k], ly.end[k] - 1
    else:
        lo_t, hi_t = min(o["toks"]), max(o["toks"])
    # 拆分点：相邻两个对上的单元之间停顿 > SPLIT_PAUSE（两边都至少 2 个单元）
    cuts = []
    for i in range(1, len(pairs)):
        gap = cells[pairs[i][0]]["s"] - cells[pairs[i - 1][0]]["e"]
        if gap > SPLIT_PAUSE and i >= 2 and len(pairs) - i >= 2:
            cuts.append(i)
    # 太长：在最靠中间的逗号处拆（逗号后面只剩语气词的不拆）
    words = [t for t in toks[lo_t:hi_t + 1] if t[1] == "w"]
    if not cuts and len(words) > LONG and "," in line:
        commas = [m.start() for m in re.finditer(",", line)]
        mid = (toks[lo_t][2] + toks[hi_t][3]) / 2
        commas = [c for c in commas if not re.fullmatch(r"[\s,\-]*(?:(?:uh|oh|ah|eh|yeah|na)[\s,\-]*)*\)?", line[c:].lower())]
        if commas:
            c = min(commas, key=lambda x: abs(x - mid))
            for i in range(1, len(pairs)):
                if toks[pairs[i][1]][2] > c >= toks[pairs[i - 1][1]][2]:
                    cuts.append(i)
                    break
    segs, prev = [], 0
    for c in cuts + [len(pairs)]:
        segs.append(pairs[prev:c])
        prev = c
    out = []
    for si, seg in enumerate(segs):
        a = toks[seg[0][1]][2] if si else toks[lo_t][2]
        b = toks[seg[-1][1]][3] if si < len(segs) - 1 else toks[hi_t][3]
        if si < len(segs) - 1:   # 拆开的前半：到下一段第一个词之前
            b = toks[segs[si + 1][0][1]][2]
        text = line[a:b].strip().rstrip(",，、")
        if si == 0 and lo_t == ly.start[k]:
            text = line[:b].strip().rstrip(",，、")
        if si == len(segs) - 1 and hi_t == ly.end[k] - 1:
            text = line[a:].strip()
        from workflow_v2.gap_fill import clean_parens
        # 括号里的（和声、喊名：(Bizarrap)、(Pa' tipos, pa'-pa'-pa' tipos como—)）只有确实对上了才显示
        got = {toks[t][2] for t in o["toks"]}
        off = line.find(text) if text in line else 0
        for m in reversed(list(re.finditer(r"\s*\([^)]*\)", text))):
            if not any(off + m.start() <= g < off + m.end() for g in got):
                text = text[:m.start()] + text[m.end():]
        out.append(([u for u, _ in seg], tidy(clean_parens(text) or text)))
    return out


# ---------------------------------------------------------------- 主流程

def run(d, lyrics, out_dir, meta=None):
    """meta：{video, offset, title, artist}，观众合唱检测看画面、取录音室版时间轴用。"""
    meta = meta or {}
    from workflow_v2.paths import read_json as _rj
    opts = {**(_rj(d / "align_options.json", {}) or {}), **(meta.get("opts") or {})}   # 只对这首歌开的规则开关（默认都关；meta 可临时覆盖，试验用）
    import librosa
    import llm
    import pysubs2
    from qwen_asr import SR

    out_dir.mkdir(parents=True, exist_ok=True)
    (d / "reports").mkdir(exist_ok=True)
    llm.load_env()
    key = os.environ["ALIYUN_BAILIAN_API_KEY"]
    cache = d / "reports" / "asr31_cache.json"
    y, _ = librosa.load(str(d / "vocals.wav"), sr=SR, mono=True)
    dur = len(y) / SR
    V2.PITCH = V2.Pitch(y, SR, d / "reports" / "pitch.npz")
    V2.STEREO = V2.Stereo(d / "vocals.wav", d / "reports" / "stereo.npz")
    beats = None
    mix = d / "audio.flac"
    if mix.exists():
        bcache = d / "reports" / "beats.npy"
        if bcache.exists():
            beats = np.load(bcache)
        else:
            ym, _ = librosa.load(str(mix), sr=SR, mono=True)
            _, bf = librosa.beat.beat_track(y=ym, sr=SR, hop_length=512)
            beats = librosa.frames_to_time(bf, sr=SR, hop_length=512)
            np.save(bcache, beats)

    lines = [l.strip() for l in lyrics if l.strip()]
    ly = Lyrics(lines)

    # 第 0 步：听
    reads, cands, sets = L.listen(y, SR, key, cache, V2.PITCH, beats)
    log = {"cut_sets": [[round(b, 1) for _, b in s[:-1]] for s in sets], "rounds": []}

    # 第 1~3 步：对齐 → 锚点 → 锚点之间重新识别 → 再对齐
    cells, path, occ = run_alignment(reads, ly)
    for rnd in range(1, ROUNDS + 1):
        added = calibrate(y, SR, key, cache, cands, reads, ly, occ, cells, dur, rnd)
        log["rounds"].append({"anchors": sum(o["anchor"] for o in occ), "lines": len(occ),
                              "relistened": [[round(w[0]["s"], 1), round(w[-1]["e"], 1)] for w in added]})
        if not added:
            break
        reads = reads + added
        cells, path, occ = run_alignment(reads, ly)
    n_reads = len(reads)

    # 顺序校准文字：上一次唱的是 Genius 上一句、下一次是下一句（夹在顺序中间），识别走样或只听到一截也显示整句，标「顺序」；
    # 不是锚点、也不在顺序中间、只对上不到 SHOW_MIN 的零碎匹配，不算歌词（交给歌词外判断）
    def step(k):   # Genius 里 k 的下一句（跳过纯语气词 / 和声行）
        k += 1
        while k < len(ly.lines) and not ly.key[k]:
            k += 1
        return k
    for i, o in enumerate(occ):
        prv = occ[i - 1]["k"] if i else None
        nxt = occ[i + 1]["k"] if i + 1 < len(occ) else None
        o["between"] = prv is not None and nxt is not None and step(prv) == o["k"] and step(o["k"]) == nxt
        # 现场改词只在「不在顺序里」时成立（同一句反复唱、每遍换词）；顺序确定的以 Genius 为准（BZRP 1:30 说唱听走样）
        if o["between"]:
            o["live_change"] = False
        o["seq"] = not o["anchor"] and o["between"] and (o["coverage"] < 0.6 or o["sim"] < 0.75)
        o["shown"] = o["anchor"] or o["between"] or o["coverage"] >= SHOW_MIN
    # 歌词范围（第一个锚点到最后一个锚点）之外没有「改词」：只可能是讲话或不出字幕，交给歌词外判断
    anc = [o for o in occ if o["anchor"]]
    lo_a, hi_a = (anc[0]["s"], anc[-1]["e"]) if anc else (0.0, 0.0)
    for o in occ:
        if o.get("live_change") and not o["anchor"] and not lo_a <= o["s"] <= hi_a:
            o["shown"] = False
    occ = [o for o in occ if o["shown"]]
    occ = fill_by_order(occ, cells, ly, y, SR)

    # 第 4 步：歌词外的段落
    matched = {u for o in occ for u in o["cells"]}
    outs, cur = [], []
    for u, c in enumerate(cells):
        if u in matched:
            if cur:
                outs.append(cur)
            cur = []
            continue
        if cur and c["s"] - cells[cur[-1]]["e"] > 1.5:
            outs.append(cur)
            cur = []
        cur.append(u)
    if cur:
        outs.append(cur)

    anchored = [o for o in occ if o["anchor"]]
    lyric_lo = anchored[0]["s"] if anchored else dur
    lyric_hi = anchored[-1]["e"] if anchored else 0.0
    rows = []
    for oi, o in enumerate(occ):
        nxt_s = occ[oi + 1]["s"] if oi + 1 < len(occ) else dur
        for ci, text in display_rows(o, ly, cells, nxt_s):
            k = o["k"]
            if o.get("filled"):   # 按顺序填的：时间是前后两句之间的空当
                rows.append({"k": k, "genius": ly.lines[k], "text": text, "lang": ly.langs[k], "heard": o["heard"],
                             "s": o["s"], "e": o["e"], "A": o["s"], "A_end": o["e"], "starts": {}, "occ": o,
                             "kind": "lyric", "n_words": 0})
                continue
            first = cells[ci[0]]
            # 各遍给的开头：这一截第一个对上的单元，各遍的起点
            starts = {}
            for u in ci:
                for cd in cells[u]["cands"]:
                    for r, (s, e) in cd["reads"].items():
                        starts.setdefault(r, s)
                if len(starts) >= n_reads:
                    break
            ends = [cells[u]["e"] for u in ci[-2:]]
            rows.append({"k": k, "genius": ly.lines[k], "text": text, "lang": ly.langs[k],
                         "heard": o["heard"],
                         "s": first["s"], "e": max(ends), "A": first["s"], "A_end": max(ends),
                         "starts": starts, "occ": o, "kind": "lyric", "n_words": len(ci)})
    from rapidfuzz import fuzz
    for seg in outs:
        cs = [cells[u] for u in seg]
        best = [max(c["cands"], key=lambda cd: len(cd["reads"])) for c in cs]
        s, e = cs[0]["s"], cs[-1]["e"]
        # 文字只用一遍的原话（这段里词最多的那遍），几遍拼起来顺序会乱
        per = [[w for w in ws if s - 0.2 <= w["s"] <= e + 0.2] for ws in reads]
        one = max(per, key=lambda ws: (len(ws), -min((w["src"] for w in ws), default=0)))
        text = V2.A3.text_of(one).strip()
        sup = sum(1 for cd in best if len(cd["reads"]) >= 2) / len(best)
        st = V2.PITCH.ratio(s, max(e, s + 1.0))
        lang = line_lang_safe(text, ly.main)
        n = units(text, lang)
        inside = lyric_lo <= s <= lyric_hi
        # 先看是不是旁边歌词的重复（几遍识别分块不同、写法不同，没合并掉的同一句）：是就不出字幕
        near = " ".join(ly.lines[o["k"]] + " " + o["heard"] for o in occ if abs(o["s"] - s) < 5 or abs(o["e"] - e) < 5)
        k1, k2 = key_of(text), key_of(near)
        dup = len(k1) >= 2 and bool(k2) and fuzz.partial_ratio(k1, k2) >= 80
        # 时间上一半以上和已经显示的歌词重叠：是那句歌词在另一遍识别里的变体（BZRP「Tu avión」= Perdón, ya cogí otro avión）
        over = sum(max(0.0, min(e, r["e"]) - max(s, r["s"])) for r in rows if r["kind"] == "lyric")
        dup = dup or over > 0.5 * max(0.3, e - s)
        # 讲话：多遍都听到、音高一直在滑；歌词范围之外本来就多半是说话（背景常有音乐），门槛放宽
        talk = not dup and bool(text) and n >= TALK_WORDS * (2 if CJK.search(text) else 1) and sup >= 0.5 and st < (TALK_STEADY if inside else TALK_STEADY_OUT)
        # 在歌词范围里、在唱、多遍都听到、像词、不是重复：现场加的内容（GIRL LIKE ME 报国家名）
        live = not dup and not talk and inside and sup >= 0.6 and V2.word_like(text, lang)
        rows.append({"k": None, "genius": "", "text": text[:1].upper() + text[1:] if live else text, "lang": lang,
                     "heard": text, "s": s, "e": e, "A": s, "A_end": e, "starts": {}, "occ": None,
                     "kind": "talk" if talk else "live" if live else "out", "steady": st, "support": sup})

    rows.sort(key=lambda r: r["s"])

    # 开头 / 结尾单独一块（隔着 ≥ BLOCK_GAP 没字幕），整块音高一直在滑：是对话（即使 Genius 收录了）
    shown = [r for r in rows if r["kind"] in ("lyric", "talk", "live")]
    for blk in (block(shown, dur, head=True), block(shown, dur, head=False)):
        if blk and V2.PITCH.ratio(blk[0]["s"], blk[-1]["e"]) < BLOCK_TALK:
            lyr_in = [r for r in blk if r.get("occ")]
            mostly_weak = bool(lyr_in) and sum(1 for r in lyr_in if not r["occ"]["anchor"]) > len(lyr_in) / 2
            for r in blk:
                # 开关 talk_block_heard（歌曲目录 align_options.json，默认关）：对话段里只是勉强对上的歌词行
                # （不是锚点）显示识别到的原话，不显示没唱的歌词（Antología 开头介绍 Dua Lipa 被对成了歌词）
                o = r.get("occ")
                if opts.get("talk_block_heard") and mostly_weak and r["kind"] == "lyric" and o and not o["anchor"] and r.get("heard"):
                    h = r["heard"]
                    r.update({"text": h[:1].upper() + h[1:], "genius": "", "talk_heard": True})
                r["kind"] = "talk"
                r["block_talk"] = True
            # 对话段里对上 Genius 的行大多是锚点（对得准，比如そばにいるね 开头对话 Genius 有收录）：保留 Genius 原文；
            # 大多不是锚点（勉强对上的，比如 Antología 开头介绍 Dua Lipa 被对成没唱的歌词）：才整段按原话重切
            lyr_in = [r for r in blk if r.get("occ")]
            weak = sum(1 for r in lyr_in if not r["occ"]["anchor"])
            mostly_weak = bool(lyr_in) and weak > len(lyr_in) / 2
            if opts.get("talk_block_heard") and mostly_weak:
                # 整段对话重新切：取一遍识别在这一段里的完整原话，按停顿（≥ 0.6 s）/ 8 个词重新分行，
                # 代替按「对错的歌词行」切出来的碎片（「Por」「Lo que」）
                s0, e0 = blk[0]["s"], blk[-1]["e"]
                per = [[w for w in ws if s0 - 0.2 <= w["s"] <= e0 + 0.2] for ws in reads]
                one = max(per, key=len)
                if one:
                    rows[:] = [r for r in rows if not (s0 - 0.2 <= r["s"] <= e0 + 0.2 and r["kind"] in ("talk", "out", "lyric"))]
                    cur, parts = [], []
                    for w in one:
                        if cur and (w["s"] - cur[-1]["e"] >= 0.6 or len(cur) >= 8):
                            parts.append(cur)
                            cur = []
                        cur.append(w)
                    if cur:
                        parts.append(cur)
                    for ws in parts:
                        t = V2.A3.text_of(ws)
                        rows.append({"k": None, "genius": "", "text": t[:1].upper() + t[1:], "lang": line_lang_safe(t, ly.main),
                                     "heard": t, "s": ws[0]["s"], "e": ws[-1]["e"], "A": ws[0]["s"], "A_end": ws[-1]["e"],
                                     "starts": {}, "occ": None, "kind": "talk", "block_talk": True, "talk_heard": True})
                    rows.sort(key=lambda r: r["s"])

    # 讲话行：按停顿 / 8 个词拆开（太长一屏放不下）
    rows = split_talk(rows, cells)

    # 第 5 步：时间
    lyr = [r for r in rows if r["kind"] == "lyric"]
    V2.A3.engine_c([r for r in lyr if r["lang"] in LATIN], y, SR, ly.main if ly.main in LATIN else "en") if ly.main in LATIN else None
    for i, r in enumerate(rows):
        if r["kind"] != "lyric":
            r["verdict_t"], r["note_t"] = "ok", ""
            continue
        src = {f"A{n}" if n < 100 else f"R{n}": s for n, s in sorted(r["starts"].items())}
        if r["lang"] in LATIN and r.get("C") is not None:
            src["C"] = r["C"]
        t, vt, note, names = vote(src) if src else (r["s"], "ok", "按顺序填，时间取前后两句之间的空当", [])
        r["agree"] = names
        r["verdict_t"], r["note_t"] = vt, note
        if t is not None:
            r["s"] = t
        if r.get("C_end") and "C" in names:
            r["e"] = r["C_end"]
        r["e"] = max(r["e"], r["s"] + 0.3)
        # 句首没对上的语气词 / 拖腔：按每个 0.3 s 往前补
        o = r["occ"]
        k = r["k"]
        if o and o["toks"] and r is first_row_of(rows, o):
            lead = [t for t in range(ly.start[k], min(o["toks"])) if ly.opt[t]]
            if lead:
                r["s"] -= min(0.3 * len(lead), 1.2)
    rows.sort(key=lambda r: r["s"])
    prev_e = 0.0
    for r in rows:
        if r["kind"] in ("lyric", "talk", "live"):
            r["s"] = max(r["s"], prev_e + 0.05) if r["s"] < prev_e else r["s"]
            prev_e = r["e"]

    # 判定
    for r in rows:
        o = r["occ"]
        if r["kind"] == "lyric":
            if o.get("live_change"):
                r["verdict"] = "live"
            elif o.get("seq"):
                r["verdict"] = "seq"
            elif o["anchor"]:
                r["verdict"] = "ok" if r["verdict_t"] == "ok" else "warn"
            else:
                r["verdict"] = "calib" if r["verdict_t"] == "ok" else "warn"
        elif r["kind"] == "talk":
            r["verdict"] = "ok"
        elif r["kind"] == "live":
            r["verdict"] = "live"
        else:
            r["verdict"] = "unconfirmed"

    # 显示时间
    shown = [r for r in rows if r["kind"] in ("lyric", "talk", "live")]
    for i, r in enumerate(shown):
        nxt = shown[i + 1]["s"] if i + 1 < len(shown) else r["e"] + 5
        r["show_e"] = min(max(r["e"] + HOLD, r["s"] + MIN_SHOW), nxt - 0.05)
    pe = 0.0
    for r in shown:
        r["show_s"] = max(pe + 0.05, r["s"] - LEAD, 0.0)
        r["show_e"] = max(r["show_e"], r["show_s"] + 0.3)
        pe = r["show_e"]

    lyr_srt, sp_srt = pysubs2.SSAFile(), pysubs2.SSAFile()
    for r in shown:
        (sp_srt if r["kind"] == "talk" else lyr_srt).events.append(
            pysubs2.SSAEvent(start=int(r["show_s"] * 1000), end=int(r["show_e"] * 1000), text=r["text"]))
    lyr_srt.save(str(out_dir / "lyrics.srt"))
    if sp_srt.events:
        sp_srt.save(str(out_dir / "speech.srt"))
    else:
        (out_dir / "speech.srt").unlink(missing_ok=True)

    table = []
    for r in rows:
        o = r["occ"]
        if r["kind"] == "lyric":
            why = (f"对上 Genius 第 {r['k'] + 1} 行（覆盖 {o['coverage']:.0%}，读音 {o['sim']:.2f}，{o['support']:.1f} 遍支持，"
                   f"置信度 {o['conf']:.2f}{'，锚点' if o['anchor'] else ''}）") if not o.get("filled") else \
                  (f"Genius 第 {r['k'] + 1} 行：前一句唱的是第 {r['k']} 行、后一句是第 {r['k'] + 2} 行附近，"
                   f"中间听到「{o['heard']}」没对上任何一句，按顺序填这句")
            if o.get("seq"):
                why += "；识别走样，但前后锚点确定了顺序，用 Genius 原文"
            if o.get("live_change"):
                why += "；多遍都听到、实词和 Genius 明显不一样：现场改词，显示听到的原话"
            if not o["natural"]:
                why += "；不是顺着上一句唱的（跳转）"
            why += f" → 时间：{r['note_t']}"
        elif r["kind"] == "live":
            why = f"Genius 里没有，在歌词中间、{r.get('support', 0):.0%} 的词多遍都听到：现场加的内容，显示听到的原话"
        elif r["kind"] == "talk":
            why = ("开头 / 结尾单独一块，整块音高一直在滑，是对话" if r.get("block_talk") else
                   f"歌词外，{r.get('support', 0):.0%} 的词多遍都听到，音高稳定度 {r.get('steady', 0):.2f}，是在说话")
        else:
            why = f"歌词外，没出字幕（{r.get('support', 0):.0%} 的词多遍听到，音高稳定度 {r.get('steady', 0):.2f}）"
        sty = V2.style_of({**r, "speech": r["kind"] == "talk", "score": 100 * (o["sim"] if o else 0)}, ly.main) \
            if r["kind"] != "out" else (None, None)
        table.append({
            "start_ms": round(r.get("show_s", r["s"]) * 1000), "end_ms": round(r.get("show_e", r["e"]) * 1000),
            "genius": r["genius"] if r["kind"] == "lyric" else "", "qwen": r["heard"],
            "text": r["text"] if r["kind"] != "out" else "", "lang": r["lang"],
            "speech": r["kind"] == "talk", "verdict": r["verdict"], "removed": r["kind"] == "out",
            "agree": r.get("agree", []), "style": sty[0], "steady": sty[1],
            "conf": round(o["conf"], 2) if o else None, "anchor": bool(o and o["anchor"]), "strategy": why})
    (out_dir / "lines.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    prof = {"main": ly.main, "langs": sorted(set(ly.langs), key=ly.langs.count, reverse=True)[:3],
            "script": "cjk" if CJK.search(" ".join(lines)) else "latin", "heard_main": ly.main, "mismatch": False,
            "reads": n_reads, **log}
    (out_dir / "profile.json").write_text(json.dumps(prof, ensure_ascii=False, indent=1))
    for i, ws in enumerate(reads, 1):
        (out_dir / f"asr_words_{i}.json").write_text(json.dumps(ws, ensure_ascii=False, indent=0))
    return table, prof


SEQ_MAX = 3   # 两句之间最多按顺序填几句


def voiced_ratio(y, sr, a, b):
    from workflow_v2.gap_fill import voiced_ratio as vr
    return vr(y, sr, a, b)


def fill_by_order(occ, cells, ly, y=None, sr=16000):
    """区间里文字走样、整句都没对上的：前后两次唱到的是 Genius 第 a、b 行，中间正好缺 1~SEQ_MAX 句，
    中间又有听到的声音（没对上任何一句）→ 按时间均分给缺的几句，用 Genius 原文，标「顺序」。
    （BZRP 3:08 听成「¿Quién es nombre…」= Claramente no es como suena；4:38 听成「La suegra y la vecina」= Con la prensa…）"""
    used = {u for o in occ for u in o["cells"]}
    out = []
    for i, o in enumerate(occ):
        out.append(o)
        if i + 1 >= len(occ):
            continue
        n = occ[i + 1]
        miss = [k for k in range(o["k"] + 1, n["k"]) if ly.key[k]]   # 纯语气词 / 和声行不填
        if not 1 <= len(miss) <= SEQ_MAX:
            continue
        free = [u for u, c in enumerate(cells) if u not in used and o["e"] <= c["s"] < n["s"]]
        t0, t1 = o["e"], n["s"]
        # 空当要够唱这几句（每句 ≥ 1.2 s），而且有人声（听到了没对上的词，或者人声明显）
        if t1 - t0 < 1.2 * len(miss) or not (free or (y is not None and voiced_ratio(y, sr, t0, t1) >= 0.3)):
            continue
        for j, k in enumerate(miss):
            a, b = t0 + (t1 - t0) * j / len(miss), t0 + (t1 - t0) * (j + 1) / len(miss)
            part = [u for u in free if a <= cells[u]["s"] < b]
            cds = [max(cells[u]["cands"], key=lambda cd: len(cd["reads"])) for u in part]
            out.append({"k": k, "cells": part, "toks": [], "filled": True, "coverage": 0.0, "sim": 0.0,
                        "support": float(np.mean([len(cd["reads"]) for cd in cds])) if cds else 0.0, "cands": cds,
                        "s": a + 0.1, "e": b - 0.1, "natural": True, "anchor": False,
                        "seq": True, "between": True, "conf": 0.0,
                        "heard": " ".join(dict.fromkeys(cd["surf"] for cd in cds)) or "（没听到）"})
    return out


def key_of(text):
    """比较用的读音串：日中韩转罗马音（行こう ikou ≈ ゆこう yukou），拉丁词转读音键。"""
    if CJK.search(text):
        return re.sub(r"[^a-z]", "", V2.A3._romaji(text).lower())
    return "".join(t[0] for t in tokens(text))


def line_lang_safe(text, main):
    try:
        return V2.line_lang(text, main)
    except Exception:  # noqa: BLE001
        return main


def first_row_of(rows, o):
    return next(r for r in rows if r.get("occ") is o)


def block(rows, dur, head=True):
    """开头（或结尾）到第一个 ≥ BLOCK_GAP 空档之间的行；要在全曲前（后）30% 内、≥ 3 行、≥ 5 s。"""
    seq = rows if head else list(reversed(rows))
    if not seq:
        return None
    blk = [seq[0]]
    for a, b in zip(seq, seq[1:]):
        gap = b["s"] - a["e"] if head else a["s"] - b["e"]
        if gap >= BLOCK_GAP:
            break
        blk.append(b)
    if len(blk) == len(seq) or len(blk) < 3:
        return None
    lo, hi = min(r["s"] for r in blk), max(r["e"] for r in blk)
    if hi - lo < 5 or (head and hi > 0.3 * dur) or (not head and lo < 0.7 * dur):
        return None
    return sorted(blk, key=lambda r: r["s"])


def split_talk(rows, cells):
    """讲话行太长时按 8 个词（日中韩 16 字）拆开，时间按词数比例分。"""
    out = []
    for r in rows:
        if r["kind"] not in ("talk", "out") or r["k"] is not None:
            out.append(r)
            continue
        words = r["text"].split()
        cap = 8   # 按空格分的词（中英混说也按词数拆；纯日文没有空格就不拆）
        if len(words) <= cap:
            out.append(r)
            continue
        n = -(-len(words) // cap)
        per = (r["e"] - r["s"]) / len(words)
        for i in range(n):
            ws = words[i * cap:(i + 1) * cap]
            s = r["s"] + per * i * cap
            out.append({**r, "text": " ".join(ws), "heard": " ".join(ws), "s": s, "e": s + per * len(ws)})
    return out


def summary(name, table, prof):
    c = Counter(r["verdict"] for r in table)
    print(f"{name}: 字幕 {sum(1 for r in table if not r['removed'])} 行（锚点 {sum(1 for r in table if r.get('anchor'))}，"
          f"校 {c['calib']}，顺序 {c['seq']}，现场改词 {c['live']}，黄 {c['warn']}，讲话 {sum(1 for r in table if r['speech'])}），"
          f"歌词外不出字幕 {c['unconfirmed']}；识别 {prof['reads']} 遍（含重新识别），"
          f"校准 {len(prof['rounds'])} 轮", flush=True)


def run_song(slug, name):
    import acoustic
    from workflow_v2.paths import Concert
    from workflow_v2.refine import sub_title
    c = Concert(slug)
    it = c.item(name)
    d = c.song_dir(it)
    out = d / "exp_v3"
    from workflow_v2.paths import read_json
    info = read_json(d / "song.json", {})
    sl, pv = info.get("slice") or [0, 0], info.get("preview") or [0, 0]
    artist = it.get("artist") or read_json(c.dir / "concert.json", {}).get("artist", "")
    meta = {"video": d / "preview.mp4", "offset": sl[0] - pv[0], "title": it["title"], "artist": artist}
    table, prof = run(d, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")], out, meta)
    from .song_translation_workflow import translate as st
    st(d, out, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")], sub_title(c, it))   # 翻译（song_translation_workflow）
    summary(it["title"], table, prof)


def run_post(name):
    from workflow_v2.paths import ROOT
    d = ROOT / "posts" / name
    out = d / "exp_v3"
    post = json.loads((d / "post" / f"{name}.json").read_text())
    song = post.get("song") or {}
    lyrics = [l.strip() for l in (d / "lyrics.txt").read_text().splitlines() if l.strip() and not l.startswith("[")]
    table, prof = run(d, lyrics, out, {"video": d / "source.mp4", "offset": 0.0, "title": song.get("title") or name,
                                       "artist": song.get("artist") or ""})
    from .song_translation_workflow import translate as st
    st(d, out, lyrics, f"《{song.get('title') or name}》 {song.get('artist') or ''}".strip())   # 翻译（song_translation_workflow）
    summary(name, table, prof)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "workflow"))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args[0] == "post":
        run_post(args[1])
    else:
        run_song(args[1], args[2])
