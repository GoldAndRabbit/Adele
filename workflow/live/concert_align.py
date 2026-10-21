# -*- coding: utf-8 -*-
"""
演唱会对齐：决定「现场唱了哪句、按什么顺序」，时间交给 MMS。复用 workflow/ 里单曲流程的零件
（qwen_dense 的 Qwen 窗口识别缓存、textnorm.reading、qwen_dense.tighten、verify_qwen），只换掉排序的 DP。

单曲流程原来的两种 dense 排序在演唱会上都会错：
  - 段落模式（单曲流程原来的默认）：进入一段就把整段输出完（没证据的句子插值补上），缩短版 / 串烧会冒出没唱的句子；
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


