# -*- coding: utf-8 -*-
"""
按音乐切单曲（方案见 docs/design/song_segmentation.md）：一首歌 = 一段连续的伴奏（含前奏、尾奏），
歌与歌之间 = 伴奏停下的空档（掌声 / 讲话 / 安静）。歌词只用来确认「这段音乐是哪首歌」（歌词核心），不定边界。

信号（每 0.5 s 一格）：
  伴奏响度   伴奏 = 整场音频 − 分离出的人声
  节拍性     伴奏起音强度前后 3 s 的周期性（音乐 0.4～0.6，掌声 / 讲话 0.1～0.3）
  噪声度     伴奏的频谱平坦度（掌声像白噪声，高；音乐有音高，低）
  人声响度   分离出的人声

判音乐停：伴奏比这首歌（歌词核心里）的中位响度低 10 dB 以上，或者像掌声（节拍性低 + 噪声度高），持续 ≥ 1 s。

    .venv/bin/python -m workflow.live.music_edges lorde_acl2026          # 只算、打印每个边界的依据
    .venv/bin/python -m workflow.live.music_edges lorde_acl2026 --write  # 写 reports/music_edges.json
"""

import sys

import numpy as np

from .paths import Concert, read_json, write_json

HOP = 0.5              # 一格 0.5 s
DROP_DB = 10.0         # 比这首歌伴奏中位响度低这么多 = 音乐停了
CLAP_BEAT, CLAP_FLAT = 0.30, 0.25   # 节拍性低于、噪声度高于这两个 = 掌声 / 人群声
MIN_OFF = 1.0          # 音乐停至少持续这么久才算
APPLAUSE_MAX = 8.0     # 音乐停后掌声最多留这么久
TALK_DB = -28.0        # 人声高于这个、同时音乐停 = 讲话
TALK_MAX = 60.0        # 歌前讲话不超过这么长，归下一首（开场白）；更长的不归任何一首
TRANS_DB, TRANS_MIN = 4.0, 3.0   # 连着唱时的过渡：节拍掉下去、伴奏轻 ≥ 4 dB，持续 ≥ 3 s
SHORT_GAP = 90.0       # 上一首音乐停到下一首开唱不超过这么久：两首紧挨着切，中间都归下一首
INTRO_PAD = 1.0        # 前奏起点往前留一点
MIN_TAIL = 6.0         # 每首最后一句之后至少留这么久（余音 + 一点掌声），下一首更早开始时让给下一首


def features(c):
    """整场每 0.5 s：伴奏 dB、人声 dB、节拍性、噪声度。缓存 reports/music_features.npz。"""
    import librosa
    cache = c.dir / "reports" / "music_features.npz"
    if cache.exists():
        z = np.load(cache)
        return {k: z[k] for k in z.files}
    sr = 16000
    mix, _ = librosa.load(str(c.audio), sr=sr, mono=True)
    voc, _ = librosa.load(str(c.vocals), sr=sr, mono=True)
    n = min(len(mix), len(voc))
    inst, voc = mix[:n] - voc[:n], voc[:n]
    hop = int(sr * HOP)
    db = lambda x: 20 * np.log10(librosa.feature.rms(y=x, frame_length=2 * hop, hop_length=hop)[0] + 1e-6)
    I, V = db(inst), db(voc)
    flat = librosa.feature.spectral_flatness(y=inst, n_fft=2048, hop_length=hop)[0]
    onset = librosa.onset.onset_strength(y=inst, sr=sr, hop_length=512)
    ofps = sr / 512
    beat = np.zeros(len(I))
    lo, hi, half = int(0.3 * ofps), int(1.0 * ofps), int(3 * ofps)
    for k in range(len(I)):
        c0 = int(k * HOP * ofps)
        w = onset[max(0, c0 - half): c0 + half]
        if len(w) < 2 * hi:
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, "full")[len(w) - 1:]
        beat[k] = (ac[lo:hi] / (ac[0] + 1e-9)).max()
    m = min(len(I), len(V), len(flat), len(beat))
    out = {"inst": I[:m], "voc": V[:m], "flat": flat[:m], "beat": beat[:m]}
    cache.parent.mkdir(exist_ok=True)
    np.savez(cache, **out)
    return out


def song_rows(c):
    """所有歌的字幕行放到整场时间上（有 reports/before_reslice 备份时用备份：改边界前的结果）。
    每行附上「这段时间实际听到的」heard_full：原始识别结果（最早的备份 before_reslice_0 里的 asr_words）里，
    落在这行时间里的词最多的那一遍（行上存的识别文字常常只是一小段）。返回 [(歌名, 起, 止, 行)]。"""
    out = []
    for it in c.song_items():
        d = c.song_dir(it)
        b = d / "reports" / "before_reslice"
        src = b if (b / "subs" / "lines.json").exists() else d
        s0 = read_json(src / "song.json", {})["slice"][0]
        b0 = d / "reports" / "before_reslice_0"
        wsrc = b0 if (b0 / "subs").exists() else src
        w0 = read_json(wsrc / "song.json", {})["slice"][0]
        reads = [[(w0 + w["s"], w["w"]) for w in read_json(f, [])] for f in sorted((wsrc / "subs").glob("asr_words_[0-9]*.json"))]
        for r in read_json(src / "subs" / "lines.json", []) or []:
            if (r.get("text") or "").strip() and r.get("verdict") != "unconfirmed":
                t0, t1 = s0 + r["start_ms"] / 1000, s0 + r["end_ms"] / 1000
                cand = [[w for t, w in rd if t0 - 0.5 <= t <= t1 + 0.5] for rd in reads]
                r = dict(r, heard_full=" ".join(max(cand, key=len)) if cand else "")
                out.append((it["name"], t0, t1, r))
    return out


def lyric_owner(c, rows, fixes=None):
    """每行字幕属于哪首歌（不管字幕流程标的是歌词还是讲话、原来在哪首的结果里），只在那首原来的范围 ± 2 分钟里找。
    先看实际听到的（识别文字）：对齐的歌词行和听到的对不上（< 70），而听到的明显更像另一首的某句（≥ 60、比原来那首高 4 分以上），
      就归那一首，字幕换成那一句（Girl, so confusing 开头「Tears for the men as if you」其实是 Man of the Year 最后一句，
      被对成了「'Cause I ride for you, Charli」）——换成哪句记在 fixes[行号] = (歌, 原句)
    否则看字幕文字和哪首的歌词对得上（≥ 85）。对不上任何一首的返回 None。"""
    import re
    from rapidfuzz import fuzz
    norm = lambda t: re.sub(r"[^\w' ]+", " ", (t or "").lower()).split()
    lyr, raw, span = {}, {}, {}
    for it in c.song_items():
        d = c.song_dir(it)
        ls = [x.strip() for x in (d / "lyrics.txt").read_text().splitlines() if x.strip() and not x.startswith("[")]
        raw[it["name"]] = [x for x in ls if norm(x)]
        lyr[it["name"]] = [" ".join(norm(x)) for x in raw[it["name"]]]
        b = d / "reports" / "before_reslice" / "song.json"
        span[it["name"]] = read_json(b if b.exists() else d / "song.json", {})["slice"]
    score = lambda t, x: fuzz.ratio(t, x) if len(x) <= len(t) + 10 else fuzz.partial_ratio(t, x)
    near = lambda t0: [n for n, (a, b) in span.items() if a - 120 <= t0 <= b + 120]
    order = [it["name"] for it in c.song_items()]

    def by_text(name, t0, r):
        w = norm(r["text"])
        best, who, own = 0, None, 0
        if len(w) >= 4:   # 太短的句子（「And I And」）在哪首歌里都找得到相似片段，不参与
            t = " ".join(w)
            for n in near(t0):
                sc = max((score(t, x) for x in lyr[n]), default=0)
                if n == name:
                    own = sc
                if sc > best:
                    best, who = sc, n
        if own >= 85:      # 原来所在那首也对得上：算原来那首（别的歌里有相似的句子不抢）
            who, best = name, own
        return who if best >= 85 else None

    owner = [by_text(name, t0, r) for name, t0, t1, r in rows]
    # 每首「靠得住」的范围：字幕文字对得上这首歌词的行
    solid = {}
    for (name, t0, t1, r), o in zip(rows, owner):
        hw = norm(r.get("heard_full") or r.get("qwen"))
        if len(hw) >= 4 and fuzz.ratio(" ".join(hw), " ".join(norm(r["text"]))) < 70:
            continue   # 文字是这首的歌词、听到的却对不上：对齐配错的，不算这首靠得住的范围
        if o == name:
            a0, b0 = solid.get(name, (t0, t1))
            solid[name] = (min(a0, t0), max(b0, t1))
    # 再看实际听到的：只看在自己这首靠得住的范围之外（开头之前 / 结尾之后）的行，只能归相邻那首（之前 → 上一首，之后 → 下一首）
    for k, (name, t0, t1, r) in enumerate(rows):
        hw = norm(r.get("heard_full") or r.get("qwen"))
        if len(hw) < 4 or r.get("speech") or name not in solid:
            continue
        a0, b0 = solid[name]
        i = order.index(name)
        nb = order[i - 1] if t0 < a0 and i > 0 else order[i + 1] if t0 > b0 and i + 1 < len(order) else None
        if nb is None:
            continue
        h = " ".join(hw)
        fit = fuzz.ratio(h, " ".join(norm(r["text"])))
        sc_nb = max(((score(h, x), j) for j, x in enumerate(lyr[nb])), default=(0, -1))
        sc_own = max((score(h, x) for x in lyr[name]), default=0)
        if fit < 70 and sc_nb[0] >= 60 and sc_nb[0] >= sc_own + 4:
            owner[k] = nb
            if fixes is not None:
                fixes[k] = (nb, raw[nb][sc_nb[1]])
    return owner


def cores(c):
    """每首歌的歌词核心（整场时间）：文字对得上这首歌词的行（含被误标成讲话的、在相邻歌结果里的）第一句开始～最后一句结束。"""
    rows = song_rows(c)
    own = lyric_owner(c, rows)
    out = []
    for it in c.song_items():
        ts = [(t0, t1) for (n, t0, t1, r), o in zip(rows, own) if o == it["name"]]
        if not ts:   # 一句都对不上（不应该）：退回这首原来结果里的歌词行
            ts = [(t0, t1) for n, t0, t1, r in rows if n == it["name"] and not r.get("speech")]
        out.append({"name": it["name"], "title": it["title"], "a": min(a for a, _ in ts), "b": max(b for _, b in ts)})
    return out


def runs(mask, k0, k1, min_len):
    """[k0, k1) 里连续为真、长度 ≥ min_len 格的区间 [(起, 止)]。"""
    out, s = [], None
    for k in range(k0, k1):
        if mask[k] and s is None:
            s = k
        if (not mask[k] or k == k1 - 1) and s is not None:
            e = k if not mask[k] else k + 1
            if e - s >= min_len:
                out.append((s, e))
            s = None
    return out


def edges(c):
    """每首的起止（整场时间）+ 依据。
    上一首结束 = 最后一句之后伴奏第一次明显变小（比这首自己伴奏的中位响度低 DROP_DB，持续 ≥ 1 s）的时刻；
    下一首开始：
      上一首音乐停 → 下一首第一句 ≤ SHORT_GAP：紧接着上一首（中间的掌声 / 讲话 / 前奏都归下一首，讲话当开场白）
      更长（大段讲话 / 长时间空场）：上一首留掌声 ≤ APPLAUSE_MAX；下一首从前奏开始（往回找伴奏重新响起的时刻），
        紧挨着前奏的 ≤ TALK_MAX 讲话也归下一首；中间剩下的不归任何一首
    连着唱（中间伴奏没停）：切在上一首最后一句后 1 s，后面的音乐算下一首前奏，标人工确认。"""
    F = features(c)
    T = lambda k: k * HOP
    K = lambda t: max(0, min(len(F["inst"]) - 1, int(t / HOP)))
    C = cores(c)
    refs = [float(np.median(F["inst"][K(x["a"]):K(x["b"]) + 1])) for x in C]
    talk = F["voc"] > TALK_DB
    res = [{"name": x["name"], "title": x["title"], "core": [round(x["a"], 1), round(x["b"], 1)], "why": []} for x in C]
    min_off = int(MIN_OFF / HOP)
    end_t = T(len(F["inst"]) - 1)

    def music_end(i, k0, k1):
        r = runs(F["inst"] < refs[i] - DROP_DB, k0, k1, min_off)
        return T(r[0][0]) if r else None

    def intro_start(i, k0, k1, with_talk=True):
        """第一句之前，往回找伴奏重新响起的时刻（最后一段「伴奏变小」的结束）；前面紧挨着 ≤ TALK_MAX 的讲话也算进来
        （第一首不算：开场前的人声多半是暖场音乐 / 主持，不是这首的开场白）。"""
        r = runs(F["inst"] < refs[i] - DROP_DB, k0, k1, min_off)
        intro = T(r[-1][1]) if r else T(k0)
        start, why = intro - INTRO_PAD, f"前奏 {intro:.1f} 开始"
        tk = [(T(s), T(e)) for s, e in runs(talk, k0, K(intro), 1)] if with_talk else []
        if tk:
            j = len(tk) - 1
            while j > 0 and tk[j][0] - tk[j - 1][1] < 5:   # 讲话连成一片（中间停顿 < 5 s）往回追
                j -= 1
            if intro - tk[j][0] <= TALK_MAX and intro - tk[-1][1] < 10:
                start = tk[j][0] - 0.5
                why = f"前面 {intro - tk[j][0]:.0f} s 讲话归这首；" + why
        return round(start, 1), why

    # 第一首：往前最多 2 分钟找前奏
    b = C[0]
    res[0]["start"], w = intro_start(0, K(max(0.0, b["a"] - 120)), K(b["a"]), with_talk=False)
    res[0]["why"].append(w)
    for i in range(1, len(C)):
        a, b = C[i - 1], C[i]
        k0, k1 = K(a["b"]), K(b["a"])
        me = music_end(i - 1, k0, k1)
        if me is None:   # 连着唱
            # 中间有一段 ≥ 3 s 节拍掉下去、伴奏也轻一些（不到「停」）：是两首之间的过渡，切在过渡开始
            # （前奏里开唱前的短停顿只有 1～2 s，不算）；没有就切在上一首最后一句后 1 s，后面的音乐算下一首前奏
            tr = runs((F["beat"] < CLAP_BEAT) & (F["inst"] < refs[i - 1] - TRANS_DB), k0, k1, int(TRANS_MIN / HOP))
            if tr:
                cut = round(T(tr[0][0]), 1)
                res[i - 1]["end"], res[i]["start"] = cut, cut
                res[i - 1]["why"].append(f"和下一首连着唱，{cut:.1f} 起节拍掉下去 {T(tr[0][1]) - T(tr[0][0]):.0f} s（过渡），切在这里")
                res[i]["why"].append(f"和上一首连着唱，过渡 {cut:.1f} 后算这首（前奏 {b['a'] - cut:.0f} s，需人工确认）")
                res[i - 1]["confirm"] = res[i]["confirm"] = True
                continue
            cut = round(a["b"] + 1.0, 1)
            res[i - 1]["end"], res[i]["start"] = cut, cut
            res[i - 1]["why"].append(f"和下一首连着唱，切在最后一句后 1 s（{cut:.1f}）")
            res[i]["why"].append(f"和上一首连着唱，上一首最后一句后的音乐算这首前奏（{b['a'] - cut:.0f} s，需人工确认）")
            res[i - 1]["confirm"] = res[i]["confirm"] = True
            continue
        if b["a"] - me <= SHORT_GAP:
            cut = round(me + 1.0, 1)
            res[i - 1]["end"], res[i]["start"] = cut, cut
            res[i - 1]["why"].append(f"音乐 {me:.1f} 停")
            res[i]["why"].append(f"紧接上一首（音乐停后 {b['a'] - me:.0f} s 开唱，中间的掌声 / 讲话 / 前奏归这首）")
        else:
            st, w = intro_start(i, K(me + 1.0), k1)
            res[i - 1]["end"] = round(min(me + APPLAUSE_MAX, st), 1)
            res[i - 1]["why"].append(f"音乐 {me:.1f} 停，留掌声到 {res[i - 1]['end']:.1f}")
            res[i]["start"] = st
            res[i]["why"].append(w + f"；中间 {st - res[i - 1]['end']:.0f} s 不归任何一首")
    # 每首最后一句之后至少留 MIN_TAIL（最后一个和弦的余音 + 一点掌声），除非下一首的歌 / 歌前讲话更早开始
    # 讲话按识别出来的讲话行算（人声分轨里有人群欢呼，按能量判会把欢呼当成讲话）
    speech = sorted(t0 for n, t0, t1, r in song_rows(c) if r.get("speech"))
    for i in range(len(C) - 1):
        a, b = C[i], C[i + 1]
        limit = b["a"] - 0.5
        sp = [t for t in speech if a["b"] + 0.5 < t < b["a"]]
        if sp:
            limit = min(limit, sp[0] - 0.3)
        want = min(a["b"] + MIN_TAIL, limit)
        if want > res[i]["end"]:
            if abs(res[i + 1]["start"] - res[i]["end"]) < 0.05:   # 两首紧挨着：下一首开头一起往后让
                res[i + 1]["start"] = round(want, 1)
            res[i]["why"].append(f"最后一句后留到 {want:.1f}（余音 + 掌声，原来 {res[i]['end']:.1f}）")
            res[i]["end"] = round(want, 1)
    # 最后一首：音乐停 + 掌声
    a = C[-1]
    me = music_end(len(C) - 1, K(a["b"]), K(min(end_t, a["b"] + 120)))
    res[-1]["end"] = round(min(end_t, (me if me is not None else a["b"] + 20) + APPLAUSE_MAX), 1)
    res[-1]["why"].append(f"音乐 {me:.1f} 停，留掌声到 {res[-1]['end']:.1f}" if me is not None else "最后一首，按最后一句 + 掌声")
    return res


def main():
    c = Concert(sys.argv[1])
    res = edges(c)
    for x in res:
        fmt = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"
        print(f"{x['title'][:20]:<20} {fmt(x['start'])} – {fmt(x['end'])}（{x['end'] - x['start']:5.1f}s）"
              f"  歌词 {fmt(x['core'][0])}–{fmt(x['core'][1])}  {'；'.join(x['why'])}")
    if "--write" in sys.argv:
        write_json(c.dir / "reports" / "music_edges.json", res)
        print(f"写入 {c.dir / 'reports' / 'music_edges.json'}")


if __name__ == "__main__":
    main()
