# -*- coding: utf-8 -*-
"""
同一位歌手的新场次复用旧场次已经定稿的翻译（在 refine 之前跑，字幕流程翻译时就会用上）：

    .venv/bin/python -m workflow.song.reuse lorde_lolla_chile2026 lorde_acl2026                      # 整场对整场
    .venv/bin/python -m workflow.song.reuse posts/ribs_toronto2022 posts/lorde_acl2026/20_ribs         # 单首对单首（单曲）

按歌名把新场次的每首歌对上旧场次的同一首（大小写、标点、favourite / favorite 这类英美拼写不计），每首写：
  zh_memory.json   译文记忆：旧场次逐句定稿的直译版 / 诗意版（{原文: {v1, v2, v3}}）。
                   原文完全一样的歌词行直接用，不再让模型翻、不再审校；现场改词、讲话、新歌照常翻译
  zh_fixed.json    旧场次的定稿表（你定的译法）合进来；没有 __title__ 的补上旧场次的中文歌名，两场歌名一致
新场次已有的 zh_fixed.json 条目不覆盖。
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.live.paths import ROOT, Concert, read_json, write_json  # noqa: E402

SPELLING = {"favourite": "favorite", "colour": "color"}


def key(title):
    t = re.sub(r"[^a-z0-9 ]", "", title.lower())
    return " ".join(SPELLING.get(w, w) for w in t.split())


def memory_of(R):
    """旧场次 result.json 的歌词行 -> {原文: {v1, v2, v3}}；同一句出现多次取第一次。"""
    out = {}
    for u in R.get("units", []):
        if u.get("type") != "歌词" or u.get("dropped") or not u.get("v2_final") or u["orig"] in out:
            continue
        out[u["orig"]] = {"v1": u.get("v1", ""), "v2": u["v2_final"], "v3": u.get("v3_final") or u["v2_final"]}
    return out


def reuse_one(dd, sd):
    """sd（已经定稿的那首）-> dd：写 zh_memory.json，合并 zh_fixed.json（补 __title__）。"""
    R = read_json(sd / "subs" / "translation" / "result.json", {}) or {}
    mem = memory_of(R)
    write_json(dd / "zh_memory.json", {"source": str(sd.relative_to(ROOT)), "lines": mem})
    fixed = read_json(dd / "zh_fixed.json", {}) or {}
    for k, v in (read_json(sd / "zh_fixed.json", {}) or {}).items():
        fixed.setdefault(k, v)
    m = re.match(r"\s*《(.+?)》", R.get("title_zh") or "")
    if m and "__title__" not in fixed:
        fixed["__title__"] = m.group(1)
    if fixed:
        write_json(dd / "zh_fixed.json", fixed)
    return len(mem), fixed


def main():
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    if a.is_dir() and b.is_dir():   # 单首对单首
        n, fixed = reuse_one(a.resolve(), b.resolve())
        print(f"{a} <- {b}：译文记忆 {n} 句，歌名《{fixed.get('__title__', '')}》，定稿表 {len(fixed)} 条")
        return
    new, old = Concert(sys.argv[1]), Concert(sys.argv[2])
    olds = {key(it["title"]): it for it in old.song_items()}
    for it in new.song_items():
        src = olds.get(key(it["title"]))
        if not src:
            print(f"{it['name']}：{old.slug} 里没有这首，照常翻译")
            continue
        n, fixed = reuse_one(new.song_dir(it).resolve(), old.song_dir(src).resolve())
        print(f"{it['name']} <- {src['name']}：译文记忆 {n} 句，歌名《{fixed.get('__title__', '')}》，定稿表 {len(fixed)} 条")


if __name__ == "__main__":
    main()
