#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推理歌词插入：ASR 认不出的地方（说唱、对唱、合唱），按参考歌词的顺序推断应该唱的句子并插入。

对每对相邻的“锚点句”A、B（不是 Yeah/Oh 这种语气词句）：
  - A、B 之间有 >= MIN_GAP 秒人声却没有（实质）字幕
  - 在参考歌词里找 A 之后最近的 B（A 在 p、B 在 q，q-p 最小且 >= 2），中间 p+1..q-1 就是推断该唱的句子
  - 这些句子按字数估算的时长和空档有声时长相符（0.4~2.5 倍）才插入，按字数比例铺在有声区间里；
    原来夹在 A、B 之间的语气词句一并替换
之后交给 refine_timing（强制对齐）定精确时间。文字只来自参考歌词。

python pipeline/infer_insert.py in.srt --ref ori_lyrics/X.txt --vocals .../vocals.wav --lang ja -o out.srt
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pysubs2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402
from align_lyrics import reading  # noqa: E402

MIN_GAP = 2.0  # 可用 --min-gap 改
FILLER = re.compile(r"^(yeah|oh+|ah+|uh+|hey|woah|whoa|na|la|ooh|baby|yo|i'm here|\W)+$", re.I)


def is_filler(text):
    t = re.sub(r"[\s,.!?、。！？()（）\-]+", " ", text.lower()).strip()
    return not t or bool(FILLER.match(t.replace(" ", ""))) or len(reading(text)) < 4


def voiced_mask(vocals):
    import librosa
    y, _ = librosa.load(vocals, sr=16000, mono=True)
    hop = 160
    k = len(y) // hop
    db = 20 * np.log10(np.sqrt((y[: k * hop].reshape(k, hop) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(25) / 25, mode="same")
    return db > np.percentile(db, 95) - 18


def ref_index(text, ref):
    """事件文字 -> 参考歌词里所有出现位置。拆过的半句按包含关系找；
    只差个语气词的变体（“... home” / “... home, yeah”）也算同一句。"""
    from rapidfuzz import fuzz

    t = text.strip()
    rt = reading(t)
    hit = set(i for i, l in enumerate(ref) if l == t or (t and (t in l or l in t) and len(reading(l)) >= 4))
    for i, l in enumerate(ref):
        rl = reading(l)
        if rt and rl and fuzz.ratio(rt, rl) >= 88:
            hit.add(i)
    return sorted(hit)


def local_repeat(ref, window=4):
    """参考里在 window 句之内反复出现的句子（桥段/叠句），实际演唱次数本来就不固定，不做换句推断。"""
    out = set()
    for i, l in enumerate(ref):
        if any(ref[j] == l for j in range(i + 1, min(len(ref), i + window + 1))):
            out.add(l)
    return out


def neighbor_fix(events, ref, vocals, lang, margin=1.0, reach=2):
    """邻句声学校验：每句和参考歌词里它前后 reach 句比声学证据，邻句明显更像（>= margin）就换成邻句。
    处理 ASR 漏掉某句、解码把下一句（或它的半句）顶到这个位置的情况。"""
    sc = acoustic.Scorer(vocals, lang)
    rep_lines = local_repeat(ref)
    swapped, prev_idx, touched = [], None, set()
    for n, e in enumerate(events):
        idx = ref_index(e.plaintext, ref)
        if not idx or is_filler(e.plaintext) or any(e.plaintext in r for r in rep_lines):
            prev_idx = idx[0] if idx else prev_idx
            continue
        p = min(idx, key=lambda i: abs(i - (prev_idx + 1)) if prev_idx is not None else i)
        t0, t1 = e.start / 1000, e.end / 1000
        cur = sc.evidence(e.plaintext, t0, t1)
        best = (cur, e.plaintext, p)
        for k in range(max(0, p - reach), min(len(ref), p + reach + 1)):
            cand = ref[k]
            if cand == e.plaintext or is_filler(cand) or cand in rep_lines:
                continue
            if any(o.plaintext == cand for o in events[max(0, n - 1):n + 2] if o is not e):
                continue
            v = sc.evidence(cand, t0, t1)
            if v > best[0]:
                best = (v, cand, k)
        if best[1] != e.plaintext and best[0] - cur >= margin:
            swapped.append({"start": round(t0, 1), "from_line": p + 1, "to_line": best[2] + 1,
                            "gain": round(best[0] - cur, 2)})
            touched.add(n)
            e.text = best[1]
            p = best[2]
        prev_idx = p
    # 同一句连续出现两次、而参考歌词里这句从不紧挨着重复：前一个应该是参考里它的上一句（ASR 漏了那句，解码拿这句顶上）
    back_to_back = {ref[k] for k in range(len(ref) - 1) if ref[k] == ref[k + 1]}
    for n in range(len(events) - 1):
        a_, b_ = events[n], events[n + 1]
        if (a_.plaintext != b_.plaintext or a_.plaintext in back_to_back or is_filler(a_.plaintext)
                or any(a_.plaintext in r for r in rep_lines)):
            continue
        for k in ref_index(a_.plaintext, ref):
            if k > 0 and not is_filler(ref[k - 1]) and (n == 0 or events[n - 1].plaintext != ref[k - 1]):
                swapped.append({"start": round(a_.start / 1000, 1), "from_line": k + 1, "to_line": k, "gain": "dup"})
                touched.add(n)
                a_.text = ref[k - 1]
                break
    # 换完后，被换掉一半的长句：剩下的另一半恢复成整句（之后 split_long 会按需再拆）
    for n, e in enumerate(events):
        if not ({n - 1, n + 1} & touched):  # 只处理紧挨着被换过的句子的半句
            continue
        if e.plaintext not in ref:
            full = [l for l in ref if e.plaintext in l]
            neigh = [o.plaintext for o in events[max(0, n - 1):n + 2] if o is not e]
            if full and not any(x in full[0] and x != full[0] for x in neigh):
                e.text = full[0]
    return swapped


def fix_boundary_word(events, ref):
    """前一句以某词结尾（如“..., I”）、后一句又以同一个词开头（“I let you ...”），而参考里有不带这个词的版本
    （“Let you ...”）——说明选到了另一遍副歌的写法，换成不重复的版本。后一句是拆过的半句时按前缀匹配。"""
    fixed = []
    for n in range(len(events) - 1):
        a_, b_ = events[n].plaintext.strip(), events[n + 1].plaintext.strip()
        m = re.search(r"[,\s]+(\S+)$", a_)
        if not m:
            continue
        w = m.group(1).lower()
        parts = b_.split(None, 1)
        if len(parts) < 2 or parts[0].lower().strip(",") != w:
            continue
        rest = parts[1]
        variants = [l for l in ref if l.lower().startswith(rest.lower()[:12]) and l.lower().startswith(rest[0].lower())]
        if not variants:
            continue
        rl = rest.lower()
        full_rest = rest if any(l.lower() == rl or l.lower().startswith(rl) for l in ref) else None
        if full_rest:
            events[n + 1].text = rest[0].upper() + rest[1:]
            fixed.append(round(events[n + 1].start / 1000, 1))
    return fixed


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--max-span", type=int, default=12, help="A、B 在参考里最多隔多少句")
    p.add_argument("--min-gap", type=float, default=MIN_GAP, help="多长的有声空档才推理插入")
    p.add_argument("--no-neighbor-fix", dest="neighbor_fix", action="store_false", help="不做邻句声学校验")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    a = p.parse_args()

    ref = [t for t, _ in acoustic.section_lines(a.ref)]
    ev = pysubs2.load(a.srt).events
    voiced = voiced_mask(a.vocals)

    class _S:  # char_count 只需要 romanize/lang
        lang = a.lang
        from refine_timing import romanize
        romanize = staticmethod(romanize)
    chars = lambda t: acoustic.char_count(_S, t)
    rates = [(e.end - e.start) / 1000 / chars(e.plaintext) for e in ev if not is_filler(e.plaintext)]
    rate = float(np.median(rates)) if rates else 0.12

    anchors = [i for i, e in enumerate(ev) if not is_filler(e.plaintext) and ref_index(e.plaintext, ref)]
    new_events, inserted, used_until = [], [], -1
    for ai, bi in zip(anchors, anchors[1:]):
        A, B = ev[ai], ev[bi]
        t0, t1 = A.end / 1000, B.start / 1000
        # 先原样保留 A 及其之前没处理的事件
        for k in range(used_until + 1, ai + 1):
            new_events.append(ev[k])
        used_until = ai
        v = voiced[int(t0 * 100):int(t1 * 100)]
        vdur = v.sum() / 100
        if vdur < a.min_gap:
            continue
        # 空档里已有实质字幕就不动
        between = ev[ai + 1:bi]
        if any(not is_filler(e.plaintext) for e in between):
            continue
        best = None
        for p_ in ref_index(A.plaintext, ref):
            for q_ in ref_index(B.plaintext, ref):
                if 2 <= q_ - p_ <= a.max_span and (best is None or q_ - p_ < best[1] - best[0]):
                    best = (p_, q_)
        if best is None:
            continue
        cand = [ref[k] for k in range(best[0] + 1, best[1]) if not is_filler(ref[k])]
        if not cand:
            continue
        need = sum(chars(t) for t in cand) * rate
        if not 0.4 * need <= vdur <= 2.5 * need + 2.0:
            continue
        idx = np.where(v)[0]
        s0, s1 = t0 + idx[0] / 100, t0 + (idx[-1] + 1) / 100
        tot = sum(chars(t) for t in cand)
        t = s0
        for text in cand:
            d = (s1 - s0) * chars(text) / tot
            new_events.append(pysubs2.SSAEvent(start=int(t * 1000), end=int((t + d) * 1000), text=text))
            inserted.append({"start": round(t, 1), "ref_line": ref.index(text) + 1})
            t += d
        used_until = bi - 1  # A、B 之间原来的语气词句丢掉
    for k in range(used_until + 1, len(ev)):
        new_events.append(ev[k])

    new_events = sorted(new_events, key=lambda e: e.start)
    swapped = neighbor_fix(new_events, ref, a.vocals, a.lang) if a.neighbor_fix else []
    boundary = fix_boundary_word(new_events, ref)
    if boundary:
        print(f"句间重复词修正 {len(boundary)} 处：" + ", ".join(f"{t}s" for t in boundary))
    out = pysubs2.SSAFile()
    out.events = new_events
    out.save(a.output)
    if a.report:
        Path(a.report).write_text(json.dumps({"inserted": inserted, "swapped": swapped, "rate": rate},
                                             ensure_ascii=False, indent=1))
    print(f"推理插入 {len(inserted)} 句：" + ", ".join(f"L{x['ref_line']}@{x['start']}s" for x in inserted))
    print(f"邻句声学校验换句 {len(swapped)} 处：" + ", ".join(f"L{x['from_line']}→L{x['to_line']}@{x['start']}s(+{x['gain']})" for x in swapped))


if __name__ == "__main__":
    main()
