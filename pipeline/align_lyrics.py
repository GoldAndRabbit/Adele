#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
识别结果 <-> 原始歌词 互相校准：文字以原始歌词为准，时间和演唱顺序以 whisper 为准。

  参考歌词: 用户提供的 txt（一行一句）或 srt（只取文字），不要求和这一版的演唱顺序一致
  识别结果: whisper --word_timestamps True --output_format json 的 json

做法（以录音为主导，适配不同编曲 / 段落顺序 / 重复副歌）:
  1. 两边都转成平假名读音（pykakasi）并归一化，汉字/假名写法不同也能对上
  2. 参考歌词先按空格/全角空格拆成短语，粒度和 whisper 片段接近（官方字幕常是两段一行的长句）
  3. 把整段识别拼成一条读音流（短语可以跨 whisper 片段），从头往后扫：在当前位置找最匹配的参考短语
     （任意顺序、可重复，rapidfuzz 模糊匹配），达标就采用、跳到短语末尾，否则前进一个字；
     文字换成参考歌词的写法，时间取对应识别字的首尾
  4. 同一原句里相邻、时间连续的短语再合并回一句（不超过 --max-width）
  5. 片段里没被任何参考句覆盖的部分保留 whisper 原文，并在报告里列出时间点，需要人工看

python pipeline/align_lyrics.py --ref ori_lyrics/X.txt --whisper work/X/whisper/vocals.json -o ori_lyrics/X.srt
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pykakasi
import pysubs2
from rapidfuzz import fuzz

MIN_SCORE = 80          # 模糊匹配分数（0~100）
MIN_SCORE_SHORT = 90    # 读音不足 5 个字的短句容易误配，要求更高
MIN_COVER = 0.7         # 参考句至少有 70% 落在这个片段里才算（防止半句被当成整句）
MIN_DUR = 800           # 每句至少显示 0.8s
LEFTOVER_MIN = 4        # 片段里剩下没覆盖的读音不少于这么多字，就保留 whisper 原文并报出来
MERGE_GAP = 400         # 同一原句的相邻短语，间隔小于这个（ms）就合并
PHRASE_SPLIT = re.compile(r"[\s\u3000]+")

_kks = pykakasi.kakasi()


def norm_char(c):
    c = unicodedata.normalize("NFKC", c).lower()
    if "ァ" <= c <= "ヶ":  # 片假名 -> 平假名
        c = chr(ord(c) - 0x60)
    return c if (c.isalnum() or "぀" <= c <= "ヿ") else ""


def reading(text):
    """文本 -> 归一化的平假名读音串。"""
    out = "".join(item["hira"] or item["orig"] for item in _kks.convert(text))
    return "".join(norm_char(c) for c in out)


def load_ref(path):
    p = Path(path)
    if p.suffix.lower() in (".srt", ".ass", ".vtt"):
        lines = [e.plaintext.replace("\n", " ") for e in pysubs2.load(str(p)).events]
    else:
        lines = p.read_text(encoding="utf-8").splitlines()
    # 去掉 [Verse] 之类的段落标记和空行
    lines = [re.sub(r"\[.*?\]", "", l).strip() for l in lines]
    return [l for l in lines if l]


def load_segments(path):
    """whisper json -> 片段列表；每个片段是 [(读音字, 开始ms, 结束ms, 所属词序号)] 和词列表。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    segs = []
    for seg in data["segments"]:
        chars, words = [], []
        for w in seg.get("words", []):
            cs = list(reading(w["word"]))
            words.append(w["word"])
            if not cs:
                continue
            s, e = w["start"] * 1000, w["end"] * 1000
            step = (e - s) / len(cs)
            for i, c in enumerate(cs):
                chars.append((c, s + i * step, s + (i + 1) * step, len(words) - 1))
        if chars:
            segs.append({"chars": chars, "words": words})
    return segs


def width(t):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in t)


def to_phrases(lines):
    """参考句 -> [(短语文字, 读音, 原句序号, 短语序号)]；读音太短的短语并到前一个。"""
    out = []
    for li, line in enumerate(lines):
        parts = [x for x in PHRASE_SPLIT.split(line) if x]
        merged = []
        for part in parts:
            if merged and len(reading(part)) < 4:
                merged[-1] += " " + part
            else:
                merged.append(part)
        if len(merged) > 1 and len(reading(merged[0])) < 4:
            merged[1] = merged[0] + " " + merged[1]
            merged = merged[1:]
        for pi, ph in enumerate(merged):
            out.append((ph, reading(ph), li, pi))
    return out


MAX_INNER_GAP = 3000    # 一个短语内部不允许跨过超过 3s 的静音
FRAGMENT_SCORE = 85     # 剩下的半句落在某个参考短语里的分数门槛


def match_at(stream, p, refs):
    """从识别流第 p 个读音字开始，找最匹配的参考短语；返回 (结束下标, 短语序号, 分数) 或 None。"""
    best = None
    for ri, (_, r, _, _) in enumerate(refs):
        if not r:
            continue
        need = MIN_SCORE_SHORT if len(r) < 5 else MIN_SCORE
        window = "".join(c[0] for c in stream[p:p + int(len(r) * 1.3) + 3])
        if len(window) < len(r) * MIN_COVER:
            continue
        al = fuzz.partial_ratio_alignment(r, window)
        # 必须从 p 附近开始匹配（锚定），否则就是后面的内容，留给后面的位置去配
        if not al or al.score < need or al.dest_start > 2 or al.dest_end <= al.dest_start:
            continue
        if len(r) > len(window) and (al.src_end - al.src_start) / len(r) < MIN_COVER:
            continue
        e = p + al.dest_end
        if any(stream[k + 1][1] - stream[k][2] > MAX_INNER_GAP for k in range(p, e - 1)):
            continue
        # 分数相近时偏向更长的短语，避免被 “yeah” 这类短词抢走
        key = len(r) * (al.score / 100) ** 2
        if best is None or key > best[0]:
            best = (key, e, ri, al.score)
    return best[1:] if best else None


def align(ref_lines, segs, max_width=40):
    refs = to_phrases(ref_lines)
    # 整段录音拼成一条读音流，短语可以跨 whisper 片段（whisper 的断句和歌词不一样）
    stream, words = [], []
    for si, seg in enumerate(segs):
        base = len(words)
        words.extend(seg["words"])
        for c, st, en, wi in seg["chars"]:
            stream.append((c, st, en, base + wi))

    events, leftovers, used_lines, scores = [], [], set(), []
    pending = []  # 还没配上的读音字下标

    def flush():
        if not pending:
            return
        # 按大静音切开，各自作为一句保留 whisper 原文
        groups, cur = [], [pending[0]]
        for k in pending[1:]:
            if stream[k][1] - stream[cur[-1]][2] > 1500 or k != cur[-1] + 1:
                groups.append(cur)
                cur = [k]
            else:
                cur.append(k)
        groups.append(cur)
        for g in groups:
            if len(g) < LEFTOVER_MIN:
                continue
            frag = "".join(stream[k][0] for k in g)
            # 半句：识别没错，只是短语被切开后剩下的一截 -> 用它所在短语的完整文字
            best = max(((fuzz.partial_ratio(frag, r), ri) for ri, (_, r, _, _) in enumerate(refs)
                        if r and len(frag) >= len(r) * 0.5), default=(0, None))
            if best[0] >= FRAGMENT_SCORE:
                text, _, li, pi = refs[best[1]]
                events.append({"text": text, "start": stream[g[0]][1], "end": stream[g[-1]][2],
                               "from": "ref", "line": li, "phrase": pi})
                used_lines.add(li)
                scores.append(best[0])
                continue
            wi = sorted({stream[k][3] for k in g})
            raw = "".join(words[i] for i in wi).strip()
            events.append({"text": raw, "start": stream[g[0]][1], "end": stream[g[-1]][2], "from": "whisper"})
            # 记下它在参考里的最佳分：高分 = 识别大概率没错，只是半句/伴唱重复
            frag_best = max((fuzz.partial_ratio(frag, r) for _, r, _, _ in refs if r), default=0)
            leftovers.append((stream[g[0]][1], stream[g[-1]][2], len(g), frag_best))
        pending.clear()

    p = 0
    while p < len(stream):
        hit = match_at(stream, p, refs)
        if hit is None:
            pending.append(p)
            p += 1
            continue
        flush()
        e, ri, sc = hit
        text, _, li, pi = refs[ri]
        events.append({"text": text, "start": stream[p][1], "end": stream[e - 1][2],
                       "from": "ref", "line": li, "phrase": pi})
        used_lines.add(li)
        scores.append(sc)
        p = e
    flush()

    events.sort(key=lambda o: o["start"])
    # 同一原句里前后相接的短语合并回一句
    merged = []
    for o in events:
        prev = merged[-1] if merged else None
        if (prev and o["from"] == "ref" and prev["from"] == "ref" and prev["line"] == o["line"]
                and o["phrase"] == prev["phrase"] + 1 and o["start"] - prev["end"] < MERGE_GAP
                and width(prev["text"]) + width(o["text"]) + 2 <= max_width):
            prev["text"] += "\u3000" + o["text"]
            prev["end"], prev["phrase"] = o["end"], o["phrase"]
        else:
            merged.append(dict(o))
    events = merged

    for k, o in enumerate(events):  # 每句最短显示时长，不压到下一句
        nxt = events[k + 1]["start"] if k + 1 < len(events) else None
        o["end"] = max(o["end"], o["start"] + MIN_DUR)
        if nxt is not None and o["end"] > nxt:
            o["end"] = max(nxt, o["start"] + 100)
    return events, leftovers, used_lines, scores


def fmt(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", required=True, help="原始歌词 txt/srt")
    p.add_argument("--whisper", required=True, help="whisper 输出的 json（需 --word_timestamps True）")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report", help="校准报告 json，默认与输出同名 .align.json")
    p.add_argument("--max-width", type=int, default=40, help="合并短语时单句最大显示宽度（全角算 2）")
    p.add_argument("--min-score", type=float, default=MIN_SCORE,
                   help=f"模糊匹配分数门槛，越低覆盖越多、误配风险越大（默认 {MIN_SCORE}）")
    p.add_argument("--min-cover", type=float, default=MIN_COVER,
                   help=f"参考短语落在片段里的最低比例（默认 {MIN_COVER}）")
    a = p.parse_args()

    globals().update(MIN_SCORE=a.min_score, MIN_COVER=a.min_cover)
    ref = load_ref(a.ref)
    segs = load_segments(a.whisper)
    events, leftovers, used, scores = align(ref, segs, a.max_width)

    subs = pysubs2.SSAFile()
    for o in events:
        subs.events.append(pysubs2.SSAEvent(start=int(o["start"]), end=int(o["end"]), text=o["text"]))
    subs.save(a.output)

    from_ref = sum(1 for o in events if o["from"] == "ref")
    report = {
        "events": len(events),
        "from_reference": from_ref,
        # 保留 whisper 原文的句子：读音能在参考里找到（半句、伴唱重复），文字大概率没错
        "from_whisper_likely_ok": [
            {"start": fmt(s), "end": fmt(e), "chars": n, "score": round(sc)} for s, e, n, sc in leftovers
            if sc >= FRAGMENT_SCORE],
        # 读音在参考里找不到：识别错误、即兴、喊话，需要人工核对
        "from_whisper_needs_review": [
            {"start": fmt(s), "end": fmt(e), "chars": n, "score": round(sc)} for s, e, n, sc in leftovers
            if sc < FRAGMENT_SCORE],
        "mean_score": round(sum(scores) / max(1, len(scores)), 1),
        "reference_lines_used": len(used),
        "reference_lines_total": len(ref),
    }
    rp = Path(a.report or Path(a.output).with_suffix(".align.json"))
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    ok, review = report["from_whisper_likely_ok"], report["from_whisper_needs_review"]
    print(f"输出 {len(events)} 句：{from_ref} 句用参考歌词的文字（平均分 {report['mean_score']}），"
          f"{len(ok)} 句是能在参考里找到的半句/伴唱（保留识别文字），{len(review)} 句需人工核对")
    print(f"参考歌词 {len(ref)} 句里用到了 {len(used)} 句（其余这一版可能没唱）")
    for x in review:
        print(f"  需核对: {x['start']} - {x['end']}  ({x['chars']} 字，最佳分 {x['score']})")
    print(f"报告: {rp}")


if __name__ == "__main__":
    main()
