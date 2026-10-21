# -*- coding: utf-8 -*-
"""
改了一首歌的起止点：不重跑对齐，按起点的时间差平移已有的字幕（字幕自适应时间差）。

    1) 从整场 audio.flac / vocals.wav 重切这首（refine.cut_audio，按旧时间轴算的缓存一起清掉）
    2) exp_v4 / exp_v3 里的逐句结果、识别结果、观众合唱段、翻译结果（含注释）、srt 都按 Δ = 新起点 − 旧起点 平移；
       落在新范围外的去掉；中文、注释不变，双语字幕从翻译结果重新生成（不调模型）
    3) 字幕预览版（720p）按新起止重切，不再前后多留（审核页表格时间 = 歌曲内时间）
    4) 水印按新长度重新生成；segments.json 记新边界（manual）
新范围里原来不在这首的部分（比如加进来的尾奏）没有字幕；要有字幕得重跑这首的 v4。

    .venv/bin/python -m workflow_v4.reslice lorde_acl2026 edges.json         # 一首一首平移 [{name, start, end, why?}]
    .venv/bin/python -m workflow_v4.reslice lorde_acl2026 music_edges.json --all   # 整场一起改：字幕按整场时间重新分到各首
"""

import json
import subprocess
import sys
from pathlib import Path

import pysubs2

from workflow_v2.align4 import tidy
from workflow_v2.paths import ROOT, Concert, read_json, write_json


def shift_exp(x, delta, dur):
    """一个结果目录（exp_v4 / exp_v3）整体平移 delta 秒，只留 [0, dur)。"""
    if not x.exists():
        return
    ms, dur_ms = round(delta * 1000), round(dur * 1000)
    f = x / "lines.json"
    if f.exists():
        out = []
        for r in json.loads(f.read_text()):
            if r.get("start_ms") is not None:
                s = r["start_ms"] - ms
                if s < 0 or s >= dur_ms:
                    continue
                for k in list(r):
                    if k.endswith("_ms") and isinstance(r[k], (int, float)):
                        r[k] = min(r[k] - ms, dur_ms)
            out.append(r)
        f.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for f in x.glob("asr_words*.json"):
        ws = [{**w, "s": round(w["s"] - delta, 3), "e": round(w["e"] - delta, 3)}
              for w in json.loads(f.read_text()) if 0 <= w["s"] - delta < dur]
        f.write_text(json.dumps(ws, ensure_ascii=False))
    f = x / "crowd.json"
    if f.exists():
        c = json.loads(f.read_text())
        c["segments"] = [{**s, "s": round(max(0.0, s["s"] - delta), 2), "e": round(min(dur, s["e"] - delta), 2)}
                         for s in c.get("segments", []) if s["e"] - delta > 0 and s["s"] - delta < dur]
        f.write_text(json.dumps(c, ensure_ascii=False, indent=1))
    f = x / "translation" / "result.json"
    if f.exists():
        R = json.loads(f.read_text())
        keep = [u for u in R["units"] if 0 <= u["start"] - ms < dur_ms]
        old = {u["i"]: k for k, u in enumerate(keep)}
        for k, u in enumerate(keep):
            u["start"] -= ms
            u["end"] = min(u["end"] - ms, dur_ms)
            u["i"] = k
        R["units"] = keep
        R["notes"] = {str(old[int(k)]): v for k, v in (R.get("notes") or {}).items() if int(k) in old}
        f.write_text(json.dumps(R, ensure_ascii=False, indent=1))
    for f in list(x.glob("*.srt")):
        if not f.stat().st_size:
            f.unlink()
            continue
        s = pysubs2.load(str(f))
        ev = []
        for e in s.events:
            e.start, e.end = e.start - ms, min(e.end - ms, dur_ms)
            if e.end > 0 and e.start < dur_ms:
                e.start = max(e.start, 0)
                ev.append(e)
        s.events = ev
        if ev:
            s.save(str(f))
        else:
            f.unlink()


def reslice(c, it, start, end, why=""):
    from workflow_v2.refine import cut_audio
    d = c.song_dir(it)
    info = read_json(d / "song.json", {})
    old = info["slice"][0]
    delta, dur = start - old, end - start
    cut_audio(c, it, {"start": start, "end": end}, force=True)
    shift_exp(d / "exp_v4", delta, dur)
    shift_exp(d / "exp_v3", delta, dur)
    sys.path.insert(0, str(ROOT / "workflow"))
    from workflow_v4.song_translation_workflow import build_outputs as b4
    if (d / "exp_v4" / "translation" / "result.json").exists():
        b4(d, d / "exp_v4")
    if (d / "exp_v3" / "translation" / "result.json").exists():
        from workflow_v3.song_translation_workflow import build_outputs as b3
        b3(d, d / "exp_v3")
    # 字幕预览版：按新起止重切，不多留
    tmp = d / "preview.partial.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(c.source),
                    "-vf", "scale=1280:-2", "-c:v", "h264_videotoolbox", "-b:v", "3500k", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(d / "preview.mp4")
    info = read_json(d / "song.json", {})
    info["preview"] = [round(start, 2), round(end, 2)]
    write_json(d / "song.json", info)
    subprocess.run([sys.executable, "-m", "workflow_v4.watermark", "song", c.slug, it["name"]], cwd=ROOT, check=True,
                   capture_output=True)
    segs = c.load("segments")
    s = next(x for x in segs["items"] if x["name"] == it["name"])
    s.update({"start": round(start, 2), "end": round(end, 2), "manual": True,
              "flags": [f for f in s.get("flags", []) if "人工" not in f and "参考" not in f] + [f"按歌词推边界：{why}" if why else "按歌词推边界"]})
    write_json(c.segments, segs)
    print(f"{it['name']}: {old:.1f} → {start:.1f}–{end:.1f}（字幕平移 {-delta:+.1f}s）", flush=True)




# ---------------------------------------------------------------- 整场一起改边界：字幕按整场时间重新分到各首

def reslice_all(c, edges):
    """edges = [{name, start, end, why}]（整场时间）。所有歌改边界前的结果（reports/before_reslice 备份）放到整场时间上，
    每首取落在自己新范围里的字幕行和翻译（不管原来在哪首的结果里，中文、注释跟着走）；
    文字对得上这首歌词、却被标成讲话的行改回歌词。改完重切音频、字幕预览版、水印，更新 segments.json。"""
    import shutil
    from workflow_v2.music_edges import lyric_owner, song_rows
    from workflow_v2.refine import cut_audio
    from workflow_v4.song_translation_workflow import build_outputs
    rows = song_rows(c)
    fixes = {}
    owner = lyric_owner(c, rows, fixes)   # fixes：听到的其实是相邻那首的某句（字幕换成那句、翻译用那首里同一句的）
    import re as _re
    nz = lambda t: " ".join(_re.sub(r"[^\w' ]+", " ", (t or "").lower()).split())
    fixed_at = {round(rows[k][1], 2): fixes[k] for k in fixes}   # 整场时间 -> (歌, 原句)
    src = {}
    for it in c.song_items():
        d = c.song_dir(it)
        b = d / "reports" / "before_reslice"
        if not (b / "exp_v4").exists():   # 第一次改：先备份
            b.mkdir(parents=True, exist_ok=True)
            shutil.copytree(d / "exp_v4", b / "exp_v4")
            shutil.copy(d / "song.json", b / "song.json")
        s0 = read_json(b / "song.json", {})["slice"][0]
        R = read_json(b / "exp_v4" / "translation" / "result.json", {}) or {}
        notes = {int(k): v for k, v in (R.get("notes") or {}).items()}
        crowd = (read_json(b / "exp_v4" / "crowd.json", {}) or {}).get("segments", [])
        src[it["name"]] = {"s0": s0, "R": R, "notes": notes, "crowd": crowd}
    for e in edges:
        it = c.item(e["name"])
        d = c.song_dir(it)
        start, end = e["start"], e["end"]
        dur_ms = round((end - start) * 1000)
        to = lambda t: round((t - start) * 1000)
        # 字幕行
        lines = []
        for k, ((n, t0, t1, r), o) in enumerate(zip(rows, owner)):
            if not (start <= t0 < end):
                continue
            r = {kk: v for kk, v in r.items() if kk != "heard_full"}
            r["text"] = tidy(r.get("text") or "")
            if k in fixes:
                r.update({"text": fixes[k][1], "genius": fixes[k][1], "speech": False, "verdict": "calib"})
            ms, s_old = to(t0), r["start_ms"]
            for k in list(r):
                if k.endswith("_ms") and isinstance(r[k], (int, float)):
                    r[k] = min(r[k] - s_old + ms, dur_ms)
            if r.get("speech") and o == e["name"]:   # 其实是这首的歌词
                r["speech"] = False
                r["verdict"] = "calib"
            lines.append(r)
        lines.sort(key=lambda r: r["start_ms"])
        # 翻译：所有歌的翻译单元放到整场时间上，取落在范围里的
        units, notes = [], {}
        for n, x in src.items():
            for u in x["R"].get("units", []):
                t = x["s0"] + u["start"] / 1000
                if start <= t < end:
                    v = dict(u)
                    v["start"], v["end"] = to(t), min(to(x["s0"] + u["end"] / 1000), dur_ms)
                    if v.get("type") == "讲话" and any(r["start_ms"] == v["start"] and not r.get("speech") for r in lines):
                        v["type"] = "歌词"
                    if u["i"] in x["notes"]:
                        v["_note"] = x["notes"][u["i"]]
                    fx = fixed_at.get(round(t, 2))
                    if fx:   # 这句其实是相邻那首的：原文换成那句，翻译用那首里同一句的
                        same = next((w for w in src[fx[0]]["R"].get("units", []) if nz(w["orig"]) == nz(fx[1])), None)
                        v.update({"orig": fx[1], "type": "歌词", "dropped": None})
                        for kk in ("v1", "v2", "v2_final", "v3", "v3_final"):
                            v[kk] = (same or {}).get(kk, "")
                        v.pop("_note", None)
                    v["orig"] = tidy(v["orig"])
                    units.append(v)
        units.sort(key=lambda u: u["start"])
        for k, u in enumerate(units):
            u["i"] = k
            if "_note" in u:
                notes[str(k)] = u.pop("_note")
        crowd = [{**s, "s": round(max(0.0, x["s0"] + s["s"] - start), 2), "e": round(min(end - start, x["s0"] + s["e"] - start), 2)}
                 for x in src.values() for s in x["crowd"] if x["s0"] + s["e"] > start and x["s0"] + s["s"] < end]
        out = d / "exp_v4"
        write_json(out / "lines.json", lines)
        R = dict(src[e["name"]]["R"])
        R.update({"units": units, "notes": notes})
        (out / "translation").mkdir(parents=True, exist_ok=True)
        write_json(out / "translation" / "result.json", R)
        if (out / "crowd.json").exists() or crowd:
            cj = read_json(out / "crowd.json", {}) or {}
            cj["segments"] = crowd
            write_json(out / "crowd.json", cj)
        for f in out.glob("*.srt"):
            f.unlink()   # 旧的 srt 时间轴不对了；审核页和成品用的是 lines.json / lyrics*.ass
        for f in out.glob("asr_words*.json"):
            f.unlink()   # 识别结果按旧切片；要重跑这首 v4 时会重新识别（有缓存）
        sys.path.insert(0, str(ROOT / "workflow"))
        build_outputs(d, out)
        # 音频、字幕预览版、水印、边界
        cut_audio(c, it, {"start": start, "end": end}, force=True)
        tmp = d / "preview.partial.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(c.source),
                        "-vf", "scale=1280:-2", "-c:v", "h264_videotoolbox", "-b:v", "3500k", "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", str(tmp)], check=True)
        tmp.replace(d / "preview.mp4")
        info = read_json(d / "song.json", {})
        info["preview"] = [round(start, 2), round(end, 2)]
        write_json(d / "song.json", info)
        subprocess.run([sys.executable, "-m", "workflow_v4.watermark", "song", c.slug, it["name"]], cwd=ROOT, check=True,
                       capture_output=True)
        segs = c.load("segments")
        s = next(x for x in segs["items"] if x["name"] == it["name"])
        s.update({"start": round(start, 2), "end": round(end, 2), "manual": True,
                  "flags": [f for f in s.get("flags", []) if "人工" not in f and "参考" not in f and "推边界" not in f]
                  + [f"按音乐推边界：{e.get('why', '')}"]})
        write_json(c.segments, segs)
        n_sp = sum(1 for r in lines if r.get("speech"))
        print(f"{it['name']}: {start:.1f}–{end:.1f}，字幕 {len(lines)} 行（讲话 {n_sp}），翻译 {len(units)} 句，注释 {len(notes)} 条", flush=True)


if __name__ == "__main__":
    c = Concert(sys.argv[1])
    E = json.loads(Path(sys.argv[2]).read_text())
    if "--all" in sys.argv:   # 整场一起改（字幕按整场时间重新分到各首）
        reslice_all(c, [{"name": e["name"], "start": e["start"], "end": e["end"], "why": e.get("why") or "；".join(e.get("why", []) if isinstance(e.get("why"), list) else [])} for e in E])
    else:
        for e in E:
            reslice(c, c.item(e["name"]), e["start"], e["end"], e.get("why", ""))
