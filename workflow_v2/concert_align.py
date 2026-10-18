# -*- coding: utf-8 -*-
"""
演唱会对齐：决定「现场唱了哪句、按什么顺序」，时间交给 MMS。复用 v1 的零件
（qwen_dense 的 Qwen 窗口识别缓存、textnorm.reading、qwen_dense.tighten、verify_qwen），只换掉排序的 DP。

v1 的两种 dense 排序在演唱会上都会错：
  - 段落模式（v1 默认）：进入一段就把整段输出完（没证据的句子插值补上），缩短版 / 串烧会冒出没唱的句子；
    同一句连唱两遍会合成一条长字幕
  - free 模式：每窗独立选最像的一句，长句里包含的短句（So they tell me … a girl like me ⊃ A girl like me）
    会抢走窗口，字幕在两句之间来回跳
这里的 DP：
  - 状态 = 段落里的每一句 + 「段间」；段内顺着往下唱，可以跳过一句（罚分），可以从任何一句退出（小罚分），
    可以从段间进入任何一段的开头（小罚分）或中间（大罚分）
  - 窗口打分 = 相似度 × 这句解释了窗口文字的多少（长句优先，短句不抢长句的窗口）
  - 只输出有识别证据的句子，不插值补齐
  - 一句的时长明显超过它该有的长度：用 MMS 比较「唱一遍」和「唱两遍」，两遍更像就拆成两条
"""

import itertools

import numpy as np

DEBUG = False
LEAD = 0.0             # 提前量统一在 refine 最后一步加（gap_fill.lead_all，0.2s），这里不加，免得补进来的句子和对齐的句子提前量不一样
PAD = 1.0              # MMS 微调范围：2.5s 识别窗口定的起止有 ±1s 的不确定（4 首实测 ±1.0 最好）
WIN, HOP = 2.5, 0.5
MIN_STRONG = 72        # 窗口和这句的相似度 >= 这个才算这句的证据
MIN_WINDOWS = 2        # 一次演唱至少要有这么多个强证据窗口
SKIP_PEN = 60.0        # 段内跳过一句
EXIT_PEN = 15.0        # 没唱完就离开这一段（最后一句离开不罚）
JUMP_PEN = 30.0        # 段间 -> 某段开头
JUMP_MID_PEN = 80.0    # 段间 -> 某段中间（缩短版直接从段中开始唱）


INTERJ = {"ah", "aah", "ahh", "oh", "ohh", "eh", "uh", "uhh", "ay", "ayy", "ai", "hey", "yeah", "yeh", "ya", "oh-oh", "na",
          "la", "mm", "mmm", "hmm", "woo", "wuh", "whoa", "ooh", "uh-huh", "huh", "ha", "hé", "he", "eh-eh", "prr", "brr",
          "rrr", "ping", "otra"}


def content(line):
    """去掉语气词（Ah-ah-ah、Ayy、Oh-eh…）后的实词。演唱会开场的欢呼会被识别成「Aha」「Uh huh」，
    只靠语气词就能匹配上「Ah-ah-ah, you're lookin' for」这种句子，所以匹配只看实词。"""
    import re
    toks = re.findall(r"[\w']+(?:-[\w']+)*", line.lower())
    keep = [t for t in toks if not all(p in INTERJ for p in t.split("-"))]
    return " ".join(keep)


def window_scores(texts, lines, reading, fuzz):
    """S[w, n]：窗口 w 的识别文字和第 n 句（只看实词）的匹配分（-50 ~ 50），乘上这句解释了窗口文字的比例。
    纯语气词的句子（Ayy, yeah / Oh-eh）不在这里打分，由 interjection_lines 在真唱的句子之间补。"""
    rr = [reading(x or "") for x in texts]
    ur = [reading(content(t)) for t in lines]
    S = np.full((len(texts), len(lines)), -50.0, dtype=np.float32)
    for w, r in enumerate(rr):
        if len(r) < 4:
            S[w] = 0.0  # 没识别出东西：不算证据，也不算反证
            continue
        for n, u in enumerate(ur):
            if len(u) < 4:      # 纯语气词的句子 / 实词太短：不能当证据
                S[w, n] = 0.0
                continue
            al = fuzz.partial_ratio_alignment(u, r)
            if not al:
                continue
            cover = (al.dest_end - al.dest_start) / max(1, len(r))   # 窗口文字有多少被这句解释
            S[w, n] = (al.score - 50) * (0.4 + 0.6 * min(1.0, cover * 1.5))
    return S


def decode(S, secs):
    """DP 解码：返回每个窗口所在的句子编号（None = 段间），以及每次「进入一句」的窗口。"""
    states = [(k, i) for k, sec in enumerate(secs) for i in range(len(sec))]
    N, W = len(states), S.shape[0]
    first = [i == 0 for _, i in states]
    last = [i == len(secs[k]) - 1 for k, i in states]
    NEG = -1e18
    dp = np.full(N + 1, NEG)
    dp[N] = 0.0
    hist = np.full((W, N + 1), -1, dtype=np.int32)
    for w in range(W):
        new = np.full(N + 1, NEG)
        src = np.full(N + 1, -1, dtype=np.int32)
        new[:N] = dp[:N] + np.maximum(S[w], 0.0)        # 停留在同一句
        new[N] = dp[N]                                   # 段间停留
        for n in range(N):                               # 离开一段 -> 段间
            v = dp[n] - (0.0 if last[n] else EXIT_PEN)
            if v > new[N]:
                new[N], src[N] = v, n
        for n in range(N):
            k, i = states[n]
            cands = [(dp[N] - (JUMP_PEN if first[n] else JUMP_MID_PEN), N)]
            if i >= 1:
                cands.append((dp[n - 1], n - 1))
            if i >= 2:
                cands.append((dp[n - 2] - SKIP_PEN, n - 2))
            for v, f in cands:
                v += S[w, n]
                if v > new[n]:
                    new[n], src[n] = v, f
        dp, hist[w] = new, src
    n = int(np.argmax(dp))
    assign, enter = [None] * W, [False] * W
    for w in range(W - 1, -1, -1):
        f = hist[w, n]
        assign[w] = None if n == N else n
        if f != -1:
            enter[w] = True
            n = f
    return states, assign, enter


def runs_from(states, secs, assign, enter, S, starts):
    """每次进入一句 = 一次演唱；只用这次演唱里的强证据窗口定时间，没有强证据的不输出。"""
    runs, w, W = [], 0, len(assign)
    while w < W:
        n = assign[w]
        if n is None:
            w += 1
            continue
        j = w
        while j + 1 < W and assign[j + 1] == n and not enter[j + 1]:
            j += 1
        strong = [x for x in range(w, j + 1) if S[x, n] >= MIN_STRONG - 50]
        if len(strong) >= MIN_WINDOWS:   # 只有一个窗口像：多半是讲话 / 欢呼里的巧合（同 v1 free 模式）
            k, i = states[n]
            runs.append([starts[min(strong)], starts[max(strong)] + WIN, secs[k][i]])
        w = j + 1
    # 歌词里同一句连写两行（So they tell me … ×2）：DP 可能在第一行只停一个窗口，先合成一条，交给 split_repeats 按声音拆
    merged = []
    for r in runs:
        if merged and merged[-1][2] == r[2] and r[0] - merged[-1][1] < 1.0:
            merged[-1][1] = max(merged[-1][1], r[1])
        else:
            merged.append(r)
    for a, b in zip(merged, merged[1:]):
        if b[0] < a[1]:
            a[1] = max(a[0] + 0.3, b[0] - 0.02)
    return merged


def expected_len(words):
    """一句大概唱多久：每个词约 0.3s（演唱会里实测：12 个词的副歌一遍约 4s）。"""
    return 0.4 + 0.3 * len(words)


def split_repeats(runs, texts, starts, lang, reading, fuzz):
    """一句的时长超过它该有的 1.6 倍：看这段时间里 Qwen 窗口文字中「这句的开头几个词」出现了几簇，
    每一簇就是唱了一遍，从每簇的位置拆开（精确起点交给后面的 MMS tighten）。"""
    from refine_timing import romanize
    rr = [reading(x or "") for x in texts]
    out = []
    for s, e, t in runs:
        words = romanize(t, lang)
        expect = expected_len(words)
        head = reading(" ".join(t.split()[:max(3, len(t.split()) // 3)]))
        if not words or e - s < 1.6 * expect or len(head) < 6:
            out.append([s, e, t])
            continue
        hits = [st for st, r in zip(starts, rr) if s - 1.0 <= st <= e - 1.0 and len(r) >= 6
                and fuzz.partial_ratio(head, r) >= 85]
        # 开头词出现的窗口按间隔分簇（同一遍会被相邻几个窗口都看到）
        clusters = []
        for st in hits:
            if clusters and st - clusters[-1][-1] <= 1.0:
                clusters[-1].append(st)
            else:
                clusters.append([st])
        # 每簇里最后一个还看得到开头词的窗口，起点大约就是这一遍开口的位置
        cuts = [max(s, c[-1] - 0.1) for c in clusters]
        cuts = [x for i, x in enumerate(cuts) if i == 0 or x - cuts[i - 1] >= 0.6 * expect]
        if DEBUG:
            print(f"  split? {s:.1f}-{e:.1f} {t[:30]} 开头词簇 {[round(c[0], 1) for c in clusters]} -> 切点 {[round(x, 1) for x in cuts]}")
        if len(cuts) < 2:
            out.append([s, e, t])
            continue
        cuts[0] = s
        bounds = cuts + [e]
        pieces = [[x0, x1] for x0, x1 in zip(bounds, bounds[1:])]
        # 不到半句长的小段并进后一段（最后一段并进前一段）
        i = 0
        while len(pieces) > 1 and i < len(pieces):
            if pieces[i][1] - pieces[i][0] < 0.5 * expect:
                if i + 1 < len(pieces):
                    pieces[i + 1][0] = pieces[i][0]
                else:
                    pieces[i - 1][1] = pieces[i][1]
                pieces.pop(i)
            else:
                i += 1
        for x0, x1 in pieces:
            out.append([x0, x1 - 0.03, t])
    return out


def head_tail(t, k=3):
    """这句的前 k 个和后 k 个实词（语气词不算）。"""
    w = content(t).split()
    return " ".join(w[:k]), " ".join(w[-k:])


def anchor(runs, texts, starts, reading, fuzz):
    """用 Qwen 窗口证据直接定每句的起止，不靠前后句挤：
    开头 = 最后一个还能识别出这句前几个实词的窗口的起点（再往后的窗口就不完整包含开头了）
    结尾 = 第一个识别出这句最后几个实词的窗口的终点
    找不到证据的保持原值。"""
    rr = [reading(x or "") for x in texts]
    out = []
    for s, e, t in runs:
        head, tail = (reading(x) for x in head_tail(t))
        lo, hi = s - 1.0, e + 1.0
        idx = [i for i, st in enumerate(starts) if lo <= st <= hi and len(rr[i]) >= 4]
        if len(head) >= 4:   # 单词句（Dale）也要：不然开头停在 DP 的粗位置，比开口早 2s
            h = [starts[i] for i in idx if fuzz.partial_ratio(head, rr[i]) >= 85]
            if h:
                # 同一遍里连续看到开头的那一簇：第一个窗口 [t, t+2.5] 刚好装下开头几个词 -> 开口 ≈ t + 2.5 - 开头时长；
                # 最后一个窗口的起点 ≈ 开口（但窗口滑过开口、只剩半截词时 Qwen 也常算匹配，会偏晚），两个估计取中间
                first = last = h[0]
                for x in h[1:]:
                    if x - last <= 1.0:
                        last = x
                    else:
                        break
                hd = 0.3 * max(1, len(head_tail(t)[0].split()))
                est = (last + max(first, first + WIN - hd - 0.3)) / 2 if last > first else last
                if len(content(t).split()) == 1:
                    # 单词句（Dale）：最早听到它的窗口里，它一般就在窗口前段（上面的估计会晚 1~2s，跑到后一句后面去）
                    est = first + 0.2
                s = max(s - 1.0, min(est, e - 0.6))
        if len(tail) >= 5:
            tt = [starts[i] for i in idx if starts[i] >= s - 0.5 and fuzz.partial_ratio(tail, rr[i]) >= 85]
            if tt:
                e = max(s + 0.6, tt[0] + WIN)
        out.append([s, e, t])
    # 保持唱的顺序：各句按窗口证据单独估的开头可能前后颠倒（Dale / No olvide' lo que vales），后一句至少晚 0.4s
    for a, b in zip(out, out[1:]):
        if b[0] < a[0] + 0.4:
            b[0] = a[0] + 0.4
            b[1] = max(b[1], b[0] + 0.6)
    for a, b in zip(out, out[1:]):
        if b[0] < a[1]:
            a[1] = max(a[0] + 0.3, b[0] - 0.05)
    return out


def align(song_dir, lang, out_srt, cache_path=None):
    import acoustic
    import librosa
    import pysubs2
    import qwen_dense
    from rapidfuzz import fuzz
    from textnorm import reading
    import json

    d = song_dir
    y, _ = librosa.load(str(d / "vocals.wav"), sr=qwen_dense.SR, mono=True)
    dur = len(y) / qwen_dense.SR
    starts = [round(t, 2) for t in np.arange(0, max(0.0, dur - 1.0), HOP)]
    cpath = cache_path or d / "reports" / "dense_cache.json"
    cache = json.loads(cpath.read_text()) if cpath.exists() else {}
    missing = [t for t in starts if f"{t:.2f}" not in cache]
    if missing:   # 缺的窗口（边界改过、平移后的缓存两头不全）当场补识别，写回缓存
        import os
        from concurrent.futures import ThreadPoolExecutor
        import llm
        from openai import OpenAI
        from qwen_asr import transcribe
        llm.load_env()
        client = OpenAI(base_url=qwen_dense.ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
        sr = qwen_dense.SR

        def one(t):
            return t, transcribe(client, y[int(t * sr):int(min(dur, t + WIN) * sr)], "auto")
        with ThreadPoolExecutor(3) as ex:
            for t, txt in ex.map(one, missing):
                if txt is not None:
                    cache[f"{t:.2f}"] = txt
        cpath.write_text(json.dumps(cache, ensure_ascii=False))
        still = [t for t in starts if f"{t:.2f}" not in cache]
        if len(still) > 0.1 * len(starts):
            raise RuntimeError(f"Qwen 窗口识别缺 {len(still)} 个窗口（接口失败），稍后重跑")
    texts = [cache.get(f"{t:.2f}") or "" for t in starts]
    secs_file = d / "lyrics_sections.txt"
    src = secs_file if secs_file.exists() else d / "lyrics.txt"
    secs = []
    for _, g in itertools.groupby(acoustic.section_lines(src), key=lambda x: x[1]):
        sec = [t for t, _ in g]
        if sec not in secs:
            secs.append(sec)
    flat = [t for sec in secs for t in sec]
    S = window_scores(texts, flat, reading, fuzz)
    states, assign, enter = decode(S, secs)
    runs = runs_from(states, secs, assign, enter, S, starts)
    runs = split_repeats(runs, texts, starts, lang, reading, fuzz)
    if DEBUG:
        for r in runs:
            print(f"  pre-tighten {r[0]:6.1f}-{r[1]:6.1f} {r[2][:40]}")
    # 起止直接用 Qwen 窗口证据定（开头词最后出现的窗口、结尾词最先出现的窗口），再用 MMS 在 ±PAD 内微调
    runs = anchor(runs, texts, starts, reading, fuzz)
    if DEBUG:
        for r in runs:
            print(f"  anchored {r[0]:6.1f}-{r[1]:6.1f} {r[2][:40]}")
    runs = qwen_dense.tighten(runs, y, lang, pad=PAD)
    # 字幕比开口提前一点出现（同 v1 --lead），不压到上一句
    prev = 0.0
    for r in runs:
        r[0] = max(prev, r[0] - LEAD)
        prev = r[1]
    subs = pysubs2.SSAFile()
    from .gap_fill import clean_parens
    for s_, e_, t in runs:
        subs.events.append(pysubs2.SSAEvent(start=int(s_ * 1000), end=int(e_ * 1000), text=clean_parens(t)))
    subs.save(str(out_srt))
    return len(runs)
