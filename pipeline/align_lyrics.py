#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
识别结果 <-> 原始歌词 互相校准：文字以原始歌词为准，时间以 whisper 逐字时间戳为准。

  参考歌词: 用户提供的 txt（一行一句，按演唱顺序）或 srt（只取文字）
  识别结果: whisper --word_timestamps True --output_format json 的 json

做法: 两边都归一化（NFKC、片假名转平假名、去标点空格、小写）后做字符级序列对齐，
每句参考歌词取它对上的识别字符的首尾时间；对不上的句子在相邻句之间插值并标记低置信度；
识别里大段对不上参考的部分（参考里省略的重复段、MC、即兴）也会报出来。

python pipeline/align_lyrics.py --ref ori_lyrics/X.txt --whisper work/X/whisper/vocals.json -o ori_lyrics/X.srt
"""

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pysubs2

MIN_CONF = 0.3       # 低于这个匹配率的句子视为没对上
MIN_DUR = 800        # 每句至少显示 0.8s
UNMATCHED_SPAN = 6   # 识别里连续这么多字对不上参考，就报出来


def norm_char(c):
    c = unicodedata.normalize("NFKC", c).lower()
    if "ァ" <= c <= "ヶ":  # 片假名 -> 平假名
        c = chr(ord(c) - 0x60)
    return c if (c.isalnum() or "぀" <= c <= "ヿ") else ""


def load_ref(path):
    p = Path(path)
    if p.suffix.lower() in (".srt", ".ass", ".vtt"):
        lines = [e.plaintext.replace("\n", " ") for e in pysubs2.load(str(p)).events]
    else:
        lines = p.read_text(encoding="utf-8").splitlines()
    # 去掉 [Verse] 之类的段落标记和空行
    lines = [re.sub(r"\[.*?\]", "", l).strip() for l in lines]
    return [l for l in lines if l]


def load_hyp(path):
    """whisper json -> [(字符, 开始ms, 结束ms)]，词内按字符均分时间。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    chars = []
    for seg in data["segments"]:
        for w in seg.get("words", []):
            cs = [norm_char(c) for c in w["word"]]
            cs = [c for c in "".join(cs)]
            if not cs:
                continue
            s, e = w["start"] * 1000, w["end"] * 1000
            step = (e - s) / len(cs)
            for i, c in enumerate(cs):
                chars.append((c, s + i * step, s + (i + 1) * step))
    return chars


def align(ref_lines, hyp):
    ref_str, ref_line = [], []
    for li, line in enumerate(ref_lines):
        for c in "".join(norm_char(c) for c in line):
            ref_str.append(c)
            ref_line.append(li)
    hyp_str = "".join(c for c, _, _ in hyp)
    sm = SequenceMatcher(None, "".join(ref_str), hyp_str, autojunk=False)

    matched = [[] for _ in ref_lines]  # 每句对上的识别字符下标
    hyp_used = [False] * len(hyp)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            matched[ref_line[a + k]].append(b + k)
            hyp_used[b + k] = True

    out = []
    for li, line in enumerate(ref_lines):
        n = sum(1 for c in line if norm_char(c))
        idx = matched[li]
        conf = len(idx) / n if n else 0
        if idx and conf >= MIN_CONF:
            out.append({"text": line, "start": hyp[idx[0]][1], "end": hyp[idx[-1]][2], "conf": conf})
        else:
            out.append({"text": line, "start": None, "end": None, "conf": conf})

    # 没对上的句子：在前后已对齐的句子之间按字数均分
    i = 0
    while i < len(out):
        if out[i]["start"] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j]["start"] is None:
            j += 1
        lo = out[i - 1]["end"] if i > 0 else 0
        hi = out[j]["start"] if j < len(out) else lo + 3000 * (j - i)
        widths = [max(1, len(out[k]["text"])) for k in range(i, j)]
        t = lo
        for k, wdt in zip(range(i, j), widths):
            d = (hi - lo) * wdt / sum(widths)
            out[k]["start"], out[k]["end"] = t, t + d
            t += d
        i = j

    # 保证时间单调、不重叠、每句最短显示时长
    for k, o in enumerate(out):
        if k > 0:
            o["start"] = max(o["start"], out[k - 1]["start"] + 100)
        nxt = out[k + 1]["start"] if k + 1 < len(out) and out[k + 1]["start"] is not None else None
        o["end"] = max(o["end"], o["start"] + MIN_DUR)
        if nxt is not None and o["end"] > nxt:
            o["end"] = max(nxt, o["start"] + 100)

    # 识别里大段没对上参考的部分
    gaps, k = [], 0
    while k < len(hyp):
        if hyp_used[k]:
            k += 1
            continue
        j = k
        while j < len(hyp) and not hyp_used[j]:
            j += 1
        if j - k >= UNMATCHED_SPAN:
            gaps.append((hyp[k][1], hyp[j - 1][2], j - k))
        k = j
    return out, gaps


def fmt(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", required=True, help="原始歌词 txt/srt")
    p.add_argument("--whisper", required=True, help="whisper 输出的 json（需 --word_timestamps True）")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report", help="校准报告 json，默认与输出同名 .align.json")
    a = p.parse_args()

    ref = load_ref(a.ref)
    hyp = load_hyp(a.whisper)
    out, gaps = align(ref, hyp)

    subs = pysubs2.SSAFile()
    for o in out:
        subs.events.append(pysubs2.SSAEvent(start=int(o["start"]), end=int(o["end"]), text=o["text"]))
    subs.save(a.output)

    low = [i + 1 for i, o in enumerate(out) if o["conf"] < MIN_CONF]
    report = {
        "lines": len(out),
        "aligned": len(out) - len(low),
        "low_confidence_lines": low,  # srt 里的序号，需要人工看时间轴
        "unmatched_sung_spans": [{"start": fmt(s), "end": fmt(e), "chars": n} for s, e, n in gaps],
        "mean_conf": round(sum(o["conf"] for o in out) / max(1, len(out)), 3),
    }
    rp = Path(a.report or Path(a.output).with_suffix(".align.json"))
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(f"参考 {len(ref)} 句，识别 {len(hyp)} 字；对齐 {report['aligned']}/{len(out)} 句，平均匹配率 {report['mean_conf']}")
    if low:
        print(f"低置信度（时间轴是插值的，需人工看）: 第 {', '.join(map(str, low))} 句")
    if gaps:
        print("识别里有、参考歌词里没有的演唱段（参考可能省略了重复段，或是 MC/即兴）:")
        for s, e, n in gaps:
            print(f"  {fmt(s)} - {fmt(e)}  ({n} 字)")
    print(f"报告: {rp}")


if __name__ == "__main__":
    main()
