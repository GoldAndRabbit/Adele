# -*- coding: utf-8 -*-
"""
把一行字幕改成讲话（原来被按顺序硬填成歌词、或识别了却没出字幕的那行），写上原话和中文，不重新识别、不调模型：

    .venv/bin/python -m workflow.song.to_talk posts/lorde_lolla_chile2026/18_ribs 30.30 "Are you with me?" "你们跟我一起吗？"
    .venv/bin/python -m workflow.song.to_talk DIR 302.58 "Have a great rest of your festival" "..." --end 307.5

SEC 是这一行现在的开始时间（秒，误差 0.1 s 内；同一时刻有多行时取有文字的那行）；--end 改结束时间。
中文写进这首的定稿表 zh_fixed.json（以后重跑翻译也不会被改掉）；改之前的 subs/ 备份到 reports/before_talk_<时间>/。
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workflow.live.paths import read_json, write_json  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("song_dir")
    p.add_argument("sec", type=float)
    p.add_argument("text")
    p.add_argument("zh")
    p.add_argument("--end", type=float)
    a = p.parse_args()
    d = Path(a.song_dir)
    s = d / "subs"
    shutil.copytree(s, d / "reports" / f"before_talk_{time.strftime('%Y%m%d-%H%M%S')}_{time.time_ns() % 10**6}" / "subs")
    ms = round(a.sec * 1000)
    L = read_json(s / "lines.json")
    hits = sorted([r for r in L if abs(r["start_ms"] - ms) <= 100], key=lambda r: not r.get("text"))
    if not hits:
        sys.exit(f"{a.sec}s 附近没有字幕行")
    r = hits[0]
    end = round(a.end * 1000) if a.end else r["end_ms"]
    r.update({"text": a.text, "qwen": a.text, "genius": "", "speech": True, "verdict": "ok", "removed": False,
              "end_ms": end, "strategy": "人工确认：讲话"})
    write_json(s / "lines.json", L)
    f = s / "translation" / "result.json"
    R = read_json(f)
    u = next((u for u in R["units"] if abs(u["start"] - r["start_ms"]) <= 100), None)
    if u is None:   # 原来是没出字幕的行（unconfirmed）：补一个翻译单元
        u = {"start": r["start_ms"], "anchor": False, "verdict": "ok", "issues": [], "locked": False}
        R["units"].append(u)
        R["units"].sort(key=lambda x: x["start"])
        for k, x in enumerate(R["units"]):   # 注释按句号挂：先记下原句号再重排
            x["_old"] = x.get("i")
        remap = {x["_old"]: k for k, x in enumerate(R["units"]) if x["_old"] is not None}
        for k_notes in ("notes", "final_notes"):
            if R.get(k_notes):
                R[k_notes] = {str(remap[int(i)]): v for i, v in R[k_notes].items() if int(i) in remap}
        for k, x in enumerate(R["units"]):
            x.pop("_old", None)
            x["i"] = k
    u.update({"orig": a.text, "heard": a.text, "type": "讲话", "end": end, "v1": a.zh, "v2": a.zh, "v3": a.zh, "dropped": None})
    write_json(f, R)
    fx = d / "zh_fixed.json"
    F = read_json(fx, {}) or {}
    F[a.text] = a.zh
    write_json(fx, F)
    from workflow.song.song_translation_workflow import build_outputs
    build_outputs(d, s)
    print(f"{d.name} {a.sec}s -> 讲话「{a.text}」/「{a.zh}」")


if __name__ == "__main__":
    main()
