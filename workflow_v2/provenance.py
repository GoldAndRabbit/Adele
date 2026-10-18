# -*- coding: utf-8 -*-
"""
每句字幕的来历：refine 每一步之后都存了一份字幕快照（reports/stages/NN_步骤.srt），
相邻两步逐句比对，得出最终每一句是哪一步生成的、后面被哪些步骤改过文字 / 时间，以及哪些句子在哪一步被去掉。
产物 reports/lines.json，审核页逐句表格用：
  [{start_ms, end_ms, genius, heard, text, strategy, removed, suspect}]
  genius = 对应的 Genius 原句（Genius 里没有就是空），heard = 逐句 Qwen 复核听到的，text = 最终字幕（被去掉的为空）
"""

import json
import re

STEP = {  # 快照名 -> (生成, 去掉, 改文字, 改时间) 时的说法
    "align": ("DP 对齐（Qwen 2.5s 窗口 + MMS）", "", "", ""),
    "fill": ("空档补词（Qwen 整段识别）", "空档补词时去掉", "", "补词时截短"),
    "verify": ("", "逐句复核分低，隐藏", "", ""),
    "drop": ("", "复核只听到一个词，当错位去掉", "", ""),
    "expected": ("", "", "补词 → 按歌词顺序该唱的 Genius 句", ""),
    "snap": ("", "", "补词 → 再听一遍对上的 Genius 句", ""),
    "rescue": ("隐藏后带前后文再听，放回", "", "", ""),
    "adopt": ("", "", "按 Qwen 听到的改词", ""),
    "gaps": ("空档里按歌词顺序补该唱的句子", "", "", ""),
    "interj": ("补纯语气词句", "", "", ""),
    "extend": ("", "", "", "口号句往前延伸"),
    "split": ("列举句拆开", "", "", "列举句对齐后挪开头"),
    "lead": ("", "", "", ""),   # 统一提前 0.2s，不算策略
}


def _load(path):
    import pysubs2
    return [{"s": e.start / 1000, "e": e.end / 1000, "t": e.plaintext.strip()} for e in pysubs2.load(str(path)).events]


def _overlap(a, b):
    return max(0.0, min(a["e"], b["e"]) - max(a["s"], b["s"]))


def _match(prev, cur):
    """同文字、开头相差 3s 内的按最近配对；剩下的按时间重叠配对（改了文字 / 拆开 / 合并）。"""
    pairs, used_p, used_c = [], set(), set()
    cand = sorted(((abs(p["s"] - c["s"]), i, j) for i, p in enumerate(prev) for j, c in enumerate(cur)
                   if p["t"] == c["t"] and abs(p["s"] - c["s"]) < 3.0))
    for _, i, j in cand:
        if i not in used_p and j not in used_c:
            pairs.append((i, j, "same"))
            used_p.add(i)
            used_c.add(j)
    for j, c in enumerate(cur):
        if j in used_c:
            continue
        ov = [(i, _overlap(prev[i], c)) for i in range(len(prev))]   # 一句可以拆成几句，所以不排除已配过的
        ov = [(i, o) for i, o in ov if o > 0.3 * max(0.1, min(c["e"] - c["s"], prev[i]["e"] - prev[i]["s"]))]
        for i, _ in ov:
            pairs.append((i, j, "changed"))
            used_p.add(i)
        if ov:
            used_c.add(j)
    return pairs, [i for i in range(len(prev)) if i not in used_p], [j for j in range(len(cur)) if j not in used_c]


def build(song_dir, lyrics):
    from .gap_fill import clean_parens
    stages = sorted((song_dir / "reports" / "stages").glob("*.srt"))
    if not stages:
        return None
    names = [re.sub(r"^\d+_", "", p.stem) for p in stages]
    lyric_set = {}
    for l in lyrics:
        lyric_set.setdefault(clean_parens(l.strip()), l.strip())
        lyric_set.setdefault(l.strip(), l.strip())
    # 每句一条来历：{hist: [说法], texts: [历次文字]}
    snap = _load(stages[0])
    lines = [{"hist": [STEP[names[0]][0]], "texts": [x["t"]], **x} for x in snap]
    removed = []
    for name, path in zip(names[1:], stages[1:]):
        born, gone, edit, move = STEP.get(name, (name, name, name, name))
        cur = _load(path)
        pairs, lost, new = _match(lines, cur)
        nxt = [None] * len(cur)
        for i, j, kind in pairs:
            old, c = lines[i], cur[j]
            if nxt[j] is None:
                nxt[j] = {"hist": list(old["hist"]), "texts": list(old["texts"]), **c}
            else:   # 几句合成一句（补词段换成一句歌词）
                nxt[j]["texts"] = nxt[j]["texts"] + [t for t in old["texts"] if t not in nxt[j]["texts"]]
            if kind == "changed" and c["t"] != old["t"]:
                label = edit or born or name
                if sum(1 for ii, _, _ in pairs if ii == i) > 1:   # 一句拆成几句
                    label = born or label
                if label and label not in nxt[j]["hist"]:
                    nxt[j]["hist"].append(label)
                if c["t"] not in nxt[j]["texts"]:
                    nxt[j]["texts"].append(c["t"])
            elif move and abs(c["s"] - old["s"]) > 0.25 and move not in nxt[j]["hist"]:
                nxt[j]["hist"].append(move)
        for j in new:
            nxt[j] = {"hist": [born or name], "texts": [cur[j]["t"]], **cur[j]}
        for i in lost:
            x = lines[i]
            removed.append({**x, "hist": x["hist"] + [gone or name]})
        lines = nxt
    rep = song_dir / "reports"
    verify = json.loads((rep / "verify_report.json").read_text()) if (rep / "verify_report.json").exists() else {}
    vlines = verify.get("lines", [])
    sus = [x for x in verify.get("suspect", []) if not x.get("hidden")]

    def heard_for(x):
        m = min(vlines, key=lambda v: abs(v["start"] - x["s"]) + (0 if v["text"] == x["t"] else 1.0), default=None)
        return (m.get("heard") or "") if m and abs(m["start"] - x["s"]) < 1.5 else ""

    def genius_for(x):
        for t in x["texts"]:
            if t in lyric_set:
                return lyric_set[t]
        return ""

    out = []
    for x in lines:
        out.append({"start_ms": round(x["s"] * 1000), "end_ms": round(x["e"] * 1000), "genius": genius_for(x),
                    "heard": heard_for(x), "text": x["t"], "strategy": " → ".join(h for h in x["hist"] if h),
                    "removed": False,
                    "suspect": next((s["score"] for s in sus if abs(s["start"] - x["s"]) < 0.4), None)})
    for x in removed:
        if any(y["t"] == x["t"] and abs(y["s"] - x["s"]) < 3.0 for y in lines):   # 隐藏后又放回的，只留最终那条
            continue
        out.append({"start_ms": round(x["s"] * 1000), "end_ms": round(x["e"] * 1000), "genius": genius_for(x),
                    "heard": heard_for(x), "text": "", "was": x["t"],
                    "strategy": " → ".join(h for h in x["hist"] if h), "removed": True, "suspect": None})
    out.sort(key=lambda r: r["start_ms"])
    (rep / "lines.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out
