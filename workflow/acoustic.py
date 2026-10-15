#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
声学打分：用 MMS_FA 的 CTC 发射概率直接“听”一段人声唱的是不是某句歌词，不依赖 whisper 识别出的文字。

  evidence(line, window) = [NLL(只有 *) - NLL(* line *)] / 字母数
  越大说明这段声音越像在唱这句；用来
    1. 体检：给现有字幕每句打分，找出“不可信”的连续段落
    2. 重解码：在不可信段落里，从全部候选句中按声学分数 + 顺序先验逐句挑选（允许跳过、重复、乱序），
       找不到够好的就留空（宁缺毋滥）

python workflow/acoustic.py ori_lyrics/X.srt --ref ori_lyrics/X.txt --vocals separated/htdemucs/X/vocals.wav --lang ja -o out.srt
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

SR = 16000


def section_lines(path):
    """参考歌词 -> [(文字, 段落名)]，段落名取 [Chorus: ...] 里冒号前的部分；srt/ass 只取文字。"""
    if Path(path).suffix.lower() in (".srt", ".ass", ".vtt"):
        import pysubs2
        return [(e.plaintext.replace("\n", " ").strip(), "?") for e in pysubs2.load(str(path)).events
                if e.plaintext.strip()]
    out, sec = [], "?"
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*\[([^\]:]+)", raw)
        if m:
            sec = m.group(1).strip()
            continue
        line = re.sub(r"\[.*?\]", "", raw).strip()
        if line:
            out.append((line, sec))
    return out


class Scorer:
    def __init__(self, vocals, lang):
        import librosa
        from refine_timing import emission_full, load_model, romanize

        self.lang, self.romanize = lang, romanize
        self.y, _ = librosa.load(vocals, sr=SR, mono=True)
        self.model, self.tokenizer, _ = load_model()
        em, self.fr = emission_full(self.model, self.y)
        self.em = F.log_softmax(em, dim=-1)
        from torchaudio.pipelines import MMS_FA
        self.star = MMS_FA.get_dict(star="*")["*"]
        self.cache = {}

    def tokens(self, text):
        words = self.romanize(text, self.lang)
        if not words:
            return []
        return [t for w in self.tokenizer(words) for t in w]

    def evidence(self, text, t0, t1):
        key = (text, round(t0, 2), round(t1, 2))
        if key in self.cache:
            return self.cache[key]
        toks = self.tokens(text)
        a, b = max(0, int(t0 * self.fr)), min(self.em.shape[0], int(t1 * self.fr))
        if not toks or b - a < len(toks) + 2:
            self.cache[key] = -9.0
            return -9.0
        lp = self.em[a:b].unsqueeze(1)
        T = torch.tensor([b - a])

        def nll(target):
            tg = torch.tensor([target])
            return F.ctc_loss(lp, tg, T, torch.tensor([len(target)]), blank=0,
                              reduction="sum", zero_infinity=True).item()

        ev = (nll([self.star]) - nll([self.star] + toks + [self.star])) / len(toks)
        self.cache[key] = ev
        return ev


def char_count(scorer, text):
    return max(1, sum(len(w) for w in scorer.romanize(text, scorer.lang)))


def decode(scorer, cand, t0, t1, rate, prev_idx, min_ev, order_bonus=0.3):
    """在 [t0, t1] 里逐句贪心解码。cand = [(文字, 参考序号)]。返回 [(start, end, 文字, 证据)]。"""
    out, t = [], t0
    while t < t1 - 0.6:
        best = None
        for text, idx in cand:
            n = char_count(scorer, text)
            exp = n * rate
            for d0 in (0.0, 0.3, 0.6, 1.0):
                for k in (0.75, 1.0, 1.3):
                    s, e = t + d0, min(t1, t + d0 + exp * k)
                    if e - s < 0.5:
                        continue
                    ev = scorer.evidence(text, s, e)
                    # 顺序先验：接着上一句往下唱的加分；跳太远不罚，允许乱序/重复
                    if prev_idx is not None and idx == prev_idx + 1:
                        ev += order_bonus
                    if best is None or ev > best[0]:
                        best = (ev, s, e, text, idx)
        if best and best[0] >= min_ev:
            ev, s, e, text, idx = best
            out.append((s, e, text, ev))
            prev_idx, t = idx, e
        else:
            t += 0.5
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt", help="当前字幕（时间轴已精校）")
    p.add_argument("--ref", required=True, help="参考歌词 txt（带 [段落] 标记更好）")
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default="en")
    p.add_argument("--min-ev", type=float, default=None, help="可信门槛（默认按本歌已对齐句子的分数分布自动定）")
    p.add_argument("--mode", choices=["score", "decode", "hybrid", "post"], default="hybrid",
                   help="hybrid（默认）：不可信段落保留原句，重解码找到明显更好的才替换，极低分的才隐藏；"
                        "decode：不可信段落整段换成重解码结果")
    p.add_argument("--replace-margin", type=float, default=0.5, help="hybrid：替换要比原句高出多少")
    p.add_argument("--hide-below", type=float, default=1.5, help="hybrid：低于门槛再减多少才隐藏")
    p.add_argument("--hide-low", action="store_true", help="解码后仍不可信的句子直接隐藏")
    p.add_argument("--no-fill-gaps", dest="fill_gaps", action="store_false",
                   help="不补空档（默认：两句之间有明显演唱却没字幕时，按声学分数插入可信的参考句）")
    p.add_argument("--no-hold-sustain", dest="hold_sustain", action="store_false",
                   help="不延长拖音（默认：句末人声还在持续时字幕留到人声停下）")
    p.add_argument("--no-trim-tail", dest="trim_tail", action="store_false",
                   help="不做句尾收紧（默认人声停了 0.8s 以上就让字幕在 0.4s 后消失）")
    p.add_argument("-o", "--output")
    p.add_argument("--report")
    a = p.parse_args()

    import pysubs2
    sc = Scorer(a.vocals, a.lang)
    subs = pysubs2.load(a.srt)
    ev = [sc.evidence(e.plaintext, e.start / 1000, e.end / 1000) for e in subs.events]
    arr = np.array(ev)
    # 门槛：已对齐句子分数的低分位，低于它算不可信
    min_ev = a.min_ev if a.min_ev is not None else float(np.percentile(arr, 25) - 0.5 * arr.std())
    low = arr < min_ev
    rep = {"lines": len(ev), "evidence_median": round(float(np.median(arr)), 3),
           "min_ev": round(min_ev, 3), "low": [int(i) + 1 for i in np.where(low)[0]]}

    if a.mode == "score":
        print(json.dumps(rep, ensure_ascii=False))
        return

    refs = section_lines(a.ref)
    cand, seen = [], set()
    for i, (text, _) in enumerate(refs):
        if text not in seen:
            seen.add(text)
            cand.append((text, i))
    durs = [(e.end - e.start) / 1000 / char_count(sc, e.plaintext) for e, l in zip(subs.events, low) if not l]
    rate = float(np.median(durs)) if durs else 0.12
    ref_index = {t: i for t, i in cand}

    # 找连续 >=2 句不可信的段落，在前后可信句之间重新解码
    events = [(e.start / 1000, e.end / 1000, e.plaintext, v) for e, v in zip(subs.events, ev)]
    out, i, stretches = [], 0, []
    if a.mode == "post":  # 结构已由 decode_global 决定，只做补空档/挤压摊开/拖音/收尾
        out, i = list(events), len(events)
    while i < len(events):
        if not low[i]:
            out.append(events[i])
            i += 1
            continue
        j = i
        while j < len(events) and low[j]:
            j += 1
        if j - i >= 2:
            t0 = events[i - 1][1] if i > 0 else events[i][0]
            t1 = events[j][0] if j < len(events) else events[j - 1][1]
            prev = ref_index.get(events[i - 1][2]) if i > 0 else None
            dec = decode(sc, cand, t0, t1, rate, prev, min_ev)
            if a.mode == "hybrid":
                orig = list(events[i:j])
                for d in dec:
                    hit = [o for o in orig if o[0] < d[1] and o[1] > d[0]]
                    if not hit or d[3] > max(o[3] for o in hit) + a.replace_margin:
                        orig = [o for o in orig if o not in hit] + [d]
                orig = [o for o in orig if o[3] >= min_ev - a.hide_below]
                dec = sorted(orig, key=lambda x: x[0])
            stretches.append({"from": round(t0, 1), "to": round(t1, 1), "before": j - i, "after": len(dec)})
            out.extend(dec)
        else:
            out.extend(events[i:j])
        i = j

    hidden = 0
    if a.hide_low:
        kept = [x for x in out if x[3] >= min_ev]
        hidden = len(out) - len(kept)
        out = kept

    y = sc.y
    hop = 160
    k = len(y) // hop
    db = 20 * np.log10(np.sqrt((y[: k * hop].reshape(k, hop) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(25) / 25, mode="same")
    voiced = db > np.percentile(db, 95) - 18
    out.sort(key=lambda x: x[0])

    inserted = 0
    if a.fill_gaps:
        # 补空档：两句字幕之间有明显演唱（>=0.5s）却没字幕 -> 用声学分数在全部参考句里找最像的，够可信才插入
        filled = []
        bounds = [(0.0, 0.0)] + [(x[0], x[1]) for x in out] + [(len(y) / SR, len(y) / SR)]
        for (_, g0), (g1, _) in zip(bounds[:-1], bounds[1:]):
            i0, i1 = int(g0 * 100), int(g1 * 100)
            if i1 - i0 < 50:
                continue
            seg = voiced[i0:i1]
            idx = np.where(seg)[0]
            if len(idx) < 50:
                continue
            s0, s1 = (i0 + idx[0]) / 100, (i0 + idx[-1] + 1) / 100
            dur = s1 - s0
            best = None
            for text, _ in cand:
                exp = char_count(sc, text) * rate
                if not 0.35 * dur <= exp <= 2.5 * dur:
                    continue
                ev_ = sc.evidence(text, max(g0, s0 - 0.2), min(g1, s1 + 0.2))
                if best is None or ev_ > best[0]:
                    best = (ev_, text)
            if best and best[0] >= min_ev:
                filled.append((s0, min(g1 - 0.05, max(s1, s0 + 0.8)), best[1], best[0]))
        inserted = len(filled)
        out = sorted(out + filled, key=lambda x: x[0])

    spread = 0
    if a.fill_gaps:
        # 挤压句摊开：连续被压得极短（<0.5 倍应有时长）的句子，连同它前面没字幕的演唱空档一起，按字数重新铺开
        exp = lambda x: char_count(sc, x[2]) * rate
        squeezed = lambda x: (x[1] - x[0]) < 0.5 * exp(x)
        i = 0
        while i < len(out):
            if not squeezed(out[i]):
                i += 1
                continue
            j = i
            while j < len(out) and squeezed(out[j]):
                j += 1
            lo = out[i - 1][1] if i > 0 else 0.0
            hi = out[j][0] if j < len(out) else out[j - 1][1]
            vi = np.where(voiced[int(lo * 100):int(hi * 100)])[0]
            if len(vi):
                lo = max(lo, lo + vi[0] / 100 - 0.1)
            if hi - lo > sum(x[1] - x[0] for x in out[i:j]) + 0.5:
                tot = sum(exp(x) for x in out[i:j])
                t = lo
                for m in range(i, j):
                    d = (hi - lo) * exp(out[m]) / tot
                    out[m] = (t, t + d, out[m][2], out[m][3])
                    t += d
                    spread += 1
            i = j

    extended = 0
    if a.hold_sustain:
        # 拖音：句子结束后人声还在持续，字幕跟着留到人声停下（不超过下一句前 0.05s，最多 +4s）
        held = []
        for n_, (s_, e_, text, v_) in enumerate(out):
            nxt = out[n_ + 1][0] if n_ + 1 < len(out) else len(y) / SR
            i = int(e_ * 100)
            j = i
            while j < len(voiced) and voiced[j] and j < int((nxt - 0.05) * 100) and j < i + 400:
                j += 1
            if j - i >= 20 and len(sc.tokens(text)) < 6:
                j = min(j, i + 50)  # Yeah/Oh 这类短语气词最多延长 0.5s，不能挂一整段
            if j - i >= 20:
                e_ = j / 100 + 0.15
                e_ = min(e_, nxt - 0.05)
                extended += 1
            held.append((s_, e_, text, v_))
        out = held

    bridged = 0
    if a.hold_sustain:
        # 短空档桥接：两句之间 < 3.5s、大部分时间有人声（多半是拖音/即兴，参考里没有对应句），前一句保持到下一句前
        br = []
        for n_, (s_, e_, text, v_) in enumerate(out):
            if n_ + 1 < len(out) and len(sc.tokens(text)) >= 6:
                nxt = out[n_ + 1][0]
                gap = nxt - e_
                seg = voiced[int(e_ * 100):int(nxt * 100)]
                if 0.3 < gap < 3.5 and len(seg) and seg.mean() >= 0.6:
                    e_ = nxt - 0.05
                    bridged += 1
            br.append((s_, e_, text, v_))
        out = br

    if a.trim_tail:
        # 句尾收紧：这句时间里人声停了超过 0.8s，字幕在停下后 0.4s 消失（最短 0.8s）
        trimmed = []
        for s_, e_, text, v_ in out:
            i0, i1 = int(s_ * 100), int(e_ * 100)
            idx = np.where(voiced[i0:i1])[0]
            if len(idx):
                last = (i0 + idx[-1]) / 100
                if e_ - last > 0.8:
                    e_ = max(s_ + 0.8, last + 0.4)
            trimmed.append((s_, e_, text, v_))
        out = trimmed

    res = pysubs2.SSAFile()
    for s, e, text, _ in out:
        res.events.append(pysubs2.SSAEvent(start=int(s * 1000), end=int(e * 1000), text=text))
    res.save(a.output)
    rep.update({"stretches": stretches, "hidden": hidden, "out_lines": len(out),
                "gap_inserted": inserted, "squeezed_spread": spread, "sustain_extended": extended,
                "bridged": bridged})
    if a.report:
        Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(ev)} 句，不可信 {int(low.sum())} 句（门槛 {min_ev:.2f}）；重解码 {len(stretches)} 段 -> 输出 {len(out)} 句，"
          f"隐藏 {hidden} 句；补空档插入 {inserted} 句；挤压句摊开 {spread} 句；拖音延长 {extended} 句")
    for s in stretches:
        print(f"  {s['from']:.1f}-{s['to']:.1f}s: {s['before']} 句 -> {s['after']} 句")


if __name__ == "__main__":
    main()
