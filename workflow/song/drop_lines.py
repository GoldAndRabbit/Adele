# -*- coding: utf-8 -*-
"""
人工核对后去掉错的字幕行（不重跑）：歌词被错放到讲话 / 喊话上、识别乱码、和相邻歌词重复的「现场改词」。

    .venv/bin/python -m workflow.song.drop_lines posts/hips_dont_lie_wyclef "57.6:And I didn't have the" "63.9:Until I saw you dancin'" --why "原因"

每项是「秒:字幕开头」，在这一秒 ±0.5 s 内、文字以它开头的行改成不出字幕（verdict unconfirmed、removed），
翻译结果里对应的句子标 dropped（写明原因），然后重新生成双语字幕。改之前的 subs/ 备份到 reports/before_drop_<时间>/。
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("song_dir")
    p.add_argument("items", nargs="+")
    p.add_argument("--why", default="人工核对：这里没唱这句")
    a = p.parse_args()
    d = Path(a.song_dir)
    out = d / "subs"
    shutil.copytree(out, d / "reports" / f"before_drop_{time.strftime("%Y%m%d-%H%M%S")}_{time.time_ns() % 100000}" / "subs")
    L = json.loads((out / "lines.json").read_text())
    rf = out / "translation" / "result.json"
    R = json.loads(rf.read_text())
    for it in a.items:
        t, head = it.split(":", 1)
        t = float(t) * 1000
        rows = [r for r in L if abs(r["start_ms"] - t) <= 500 and (r.get("text") or "").startswith(head) and not r.get("removed")]
        units = [u for u in R["units"] if abs(u["start"] - t) <= 700 and u["orig"].startswith(head) and not u.get("dropped")]
        for r in rows:
            r.update({"text": "", "verdict": "unconfirmed", "removed": True, "strategy": (r.get("strategy") or "") + f"；人工去掉：{a.why}"})
        for u in units:
            u["dropped"] = a.why
        print(f"{it}：字幕 {len(rows)} 行、翻译 {len(units)} 句" + ("" if rows else "  ← 没找到，检查时间和开头文字"))
    (out / "lines.json").write_text(json.dumps(L, ensure_ascii=False, indent=1))
    rf.write_text(json.dumps(R, ensure_ascii=False, indent=1))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from workflow.song.song_translation_workflow import build_outputs
    build_outputs(d, out)


if __name__ == "__main__":
    main()
