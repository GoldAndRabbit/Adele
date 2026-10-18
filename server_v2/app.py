# -*- coding: utf-8 -*-
"""v2 审核页：场次 / 单曲 API + 静态前端（web_v2/，纯 JS，前端结构拷自 SubDub）。

    .venv/bin/python -m workflow_v2 serve        # → http://127.0.0.1:8160

和 SubDub 只读后台不同，这里有三个写操作，都只写 concerts/<slug>/ 下的 JSON、不碰视频：
  POST .../review    保存选中的封面、标题、介绍、标签、备注、审核状态（review.json）
  POST .../segment   人工调整这首的起止（segments.json，manual=true；之后要重跑 refine）
  POST .../rerun     后台重跑这一首的 refine（边界改过之后），一次只跑一个
"""

import subprocess
import sys
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import workflow_v2  # noqa: E402,F401  （把 workflow/ 加进 sys.path）
from workflow_v2 import review  # noqa: E402
from workflow_v2.package import cover_candidates  # noqa: E402
from workflow_v2.paths import CONCERTS, VENV_PY, Concert, read_json, write_json  # noqa: E402

app = FastAPI(title="adele v2 review")
JOBS = {}  # (concert, name) -> {"proc", "started", "log"}


def concert(slug):
    c = Concert(slug)
    if not c.info.exists() or c.dir.parent != CONCERTS:
        raise HTTPException(404, "没有这个场次")
    return c


def song(c, name):
    try:
        it = c.item(name)
    except KeyError:
        raise HTTPException(404, "没有这首歌")
    if it["kind"] != "song":
        raise HTTPException(400, "过场不审核")
    return it


def job_state(c, name):
    j = JOBS.get((c.slug, name))
    if not j:
        return None
    code = j["proc"].poll()
    return {"running": code is None, "exit": code, "started": j["started"], "log": str(j["log"])}


def song_summary(c, it, segs, rv):
    d = c.song_dir(it)
    seg = segs.get(it["name"], {})
    st = review.song_status(c, it)
    entry = rv["songs"].get(it["name"], {})
    covers = cover_candidates(d)
    chosen = next((x for x in covers if x["id"] == entry.get("cover")), None)
    return {
        "idx": it["idx"], "name": it["name"], "title": it["title"], "notes": it.get("notes"),
        "start": seg.get("start"), "end": seg.get("end"), "confidence": seg.get("confidence"),
        "flags": seg.get("flags", []), "manual": bool(seg.get("manual")),
        "stage": st["stage"], "review": st["review"], "needs_refine": st["needs_refine"],
        "thumb": f"/media/{c.slug}/songs/{it['name']}/{(chosen or (covers[0] if covers else {})).get('file')}" if covers else None,
        "job": job_state(c, it["name"]),
    }


@app.get("/api/concerts")
def list_concerts():
    out = []
    for p in sorted(CONCERTS.iterdir()) if CONCERTS.exists() else []:
        if (p / "concert.json").exists():
            c = Concert(p.name)
            info = read_json(c.info)
            out.append({"slug": p.name, "title": info.get("title") or p.name, "artist": info.get("artist"),
                        "date": info.get("date"), "songs": len(c.song_items())})
    return out


@app.get("/api/concerts/{slug}")
def get_concert(slug: str):
    c = concert(slug)
    seg = c.load("segments") or {}
    segs = {s["name"]: s for s in seg.get("items", [])}
    rv = review.load(c)
    info = read_json(c.info)
    return {
        "slug": slug, "info": {k: info.get(k) for k in ("title", "artist", "date", "venue", "city", "tour", "duration",
                                                         "fps", "width", "height", "audio_rate", "setlist_url")},
        "source": f"/media/{slug}/source.mp4" if c.source.exists() else None,
        "items": [{"idx": it["idx"], "name": it["name"], "title": it["title"], "kind": it["kind"]} for it in c.items()],
        "songs": [song_summary(c, it, segs, rv) for it in c.song_items()],
        "gaps": seg.get("gaps", []),
    }


def ass_lines(path):
    """lyrics.ass 的每条字幕：{start, end, style, orig, zh}（片段内时间）。"""
    import pysubs2
    out = []
    for e in pysubs2.load(str(path)).events:
        parts = [x.strip() for x in e.text.replace("\\n", "\\N").split("\\N")]
        clean = [pysubs2.SSAEvent(text=x).plaintext.strip() for x in parts]
        out.append({"start": e.start / 1000, "end": e.end / 1000, "style": e.style,
                    "orig": clean[0] if clean else "", "zh": clean[1] if len(clean) > 1 else ""})
    return out


@app.get("/api/concerts/{slug}/songs/{name}")
def get_song(slug: str, name: str):
    c = concert(slug)
    it = song(c, name)
    d = c.song_dir(it)
    segs = {s["name"]: s for s in (c.load("segments") or {}).get("items", [])}
    rv = review.load(c)
    base = song_summary(c, it, segs, rv)
    lines = ass_lines(d / "lyrics.ass") if (d / "lyrics.ass").exists() else []
    # v1 逐句 Qwen 复核（verify_qwen.py）：声音里听着不像这句、但没隐藏的「可疑句」标红；每句实际听到的文字并列显示
    verify = read_json(d / "reports" / "verify_report.json", {}) or {}
    for ln in lines:
        m = min(verify.get("lines", []), key=lambda x: abs(x["start"] - ln["start"]), default=None)
        if m and abs(m["start"] - ln["start"]) < 0.3 and m["text"] == ln["orig"]:
            ln["heard"] = m["heard"]
    sus = [x for x in verify.get("suspect", []) if not x.get("hidden")]
    for ln in lines:
        if ln["style"] != "Default" or not verify:
            continue
        ln["checked"] = True
        m = next((x for x in sus if abs(x["start"] - ln["start"]) < 0.15), None)
        ln["suspect"] = m["score"] if m else None
    # 每句字幕的来源：genius = Genius 歌词按声音对齐；asr = 空档里 Qwen 识别补的词；
    # asr_lyric = 空档里 Qwen 识别出来、和某句 Genius 歌词很像，用 Genius 写法；adopt = 现场改词，Genius 原词换成 Qwen 听到的
    for ln in lines:
        ln["source"] = "speech" if ln["style"] != "Default" else ("title" if ln["orig"].startswith("《") else "genius")
    for x in read_json(d / "reports" / "asr_lines.json", []) or []:
        m = min(lines, key=lambda ln: abs(ln["start"] - x["start"]), default=None)
        if m and abs(m["start"] - x["start"]) < 0.4:
            src = x.get("source") or ("adopt" if x.get("was") else
                                      "asr" if x["text"].lower() == x["heard"].strip(" .").lower() else "asr_lyric")
            m.update({"source": src, "was": x.get("was"), "asr_heard": x["heard"]})
    info = read_json(d / "song.json", {})
    # 逐句表格：provenance.py 生成的每句来历（Genius 原句 / Qwen 复核听到 / 最终字幕 / 校准策略），加上讲话和片头
    rows = []
    for r in read_json(d / "reports" / "lines.json", []) or []:
        t = r["start_ms"] / 1000
        m = next((x for x in lines if abs(x["start"] - t) < 0.06 and x["orig"] == r["text"]), None) if r["text"] else None
        rows.append({**r, "zh": m["zh"] if m else "", "start": t, "end": r["end_ms"] / 1000})
    if rows:
        for x in lines:
            if x["style"] != "Default" or x["orig"].startswith("《"):
                rows.append({"start_ms": round(x["start"] * 1000), "end_ms": round(x["end"] * 1000), "start": x["start"],
                             "end": x["end"], "genius": "", "heard": "", "text": x["orig"], "zh": x["zh"], "removed": False,
                             "strategy": "片头歌名" if x["orig"].startswith("《") else "讲话（Qwen 识别，两遍复听都对上）",
                             "speech": x["style"] != "Default"})
        rows.sort(key=lambda r: r["start_ms"])
    # 新流程的实验结果（songs/<nn>/exp/，align3.py）：审核页上可以切换着对比，不影响正式字幕
    exp = None
    if (d / "exp" / "lines.json").exists():
        xl = ass_lines(d / "exp" / "lyrics.ass") if (d / "exp" / "lyrics.ass").exists() else []
        xrows = []
        for r in read_json(d / "exp" / "lines.json", []) or []:
            t = (r["start_ms"] or 0) / 1000
            m = next((x for x in xl if abs(x["start"] - t) < 0.06 and x["orig"] == r["text"]), None) if r["text"] else None
            xrows.append({**r, "zh": m["zh"] if m else "", "start": t, "end": (r["end_ms"] or 0) / 1000})
        exp = {"rows": xrows, "ass": f"/media/{slug}/songs/{name}/exp/lyrics.ass" if (d / "exp" / "lyrics.ass").exists() else None}
    return {
        **base,
        "exp": exp,
        "artist": it.get("artist"), "parts": it.get("parts"), "lang": info.get("lang"),
        "genius_urls": info.get("genius_urls", []), "slice": info.get("slice"),
        "lyric_start": segs.get(name, {}).get("lyric_start"), "lyric_end": segs.get(name, {}).get("lyric_end"),
        "ass": f"/media/{slug}/songs/{name}/lyrics.ass" if (d / "lyrics.ass").exists() else None,
        "preview": f"/media/{slug}/songs/{name}/preview.mp4" if (d / "preview.mp4").exists() else None,
        "preview_span": info.get("preview"), "align": info.get("align"),
        "lines": lines,
        "rows": rows,
        "covers": [{**x, "file": f"/media/{slug}/songs/{name}/{x['file']}",
                    "file_4x3": f"/media/{slug}/songs/{name}/{x['file_4x3']}" if x["file_4x3"] else None}
                   for x in cover_candidates(d)],
        "draft": read_json(d / "post_draft.json", {}),
        "review_entry": rv["songs"].get(name, {}),
    }


@app.post("/api/concerts/{slug}/songs/{name}/review")
def post_review(slug: str, name: str, body: dict = Body(...)):
    c = concert(slug)
    it = song(c, name)
    try:
        entry = review.save_entry(c, it, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"entry": entry, "review": review.effective(c, it, entry)}


@app.post("/api/concerts/{slug}/songs/{name}/segment")
def post_segment(slug: str, name: str, body: dict = Body(...)):
    c = concert(slug)
    song(c, name)
    start, end = float(body["start"]), float(body["end"])
    if not 0 <= start < end:
        raise HTTPException(400, "起止时间不对")
    seg = c.load("segments")
    items = seg["items"]
    k = next(i for i, s in enumerate(items) if s["name"] == name)
    prev = next((s for s in reversed(items[:k]) if s.get("end") is not None), None)
    nxt = next((s for s in items[k + 1:] if s.get("start") is not None), None)
    if (prev and start < prev["end"] - 0.01) or (nxt and end > nxt["start"] + 0.01):
        raise HTTPException(400, "和相邻的歌重叠了：先调那一首")
    items[k].update({"start": round(start, 2), "end": round(end, 2), "manual": True})
    write_json(c.segments, seg)
    return song_summary(c, c.item(name), {s["name"]: s for s in items}, review.load(c))


@app.post("/api/concerts/{slug}/songs/{name}/rerun")
def post_rerun(slug: str, name: str):
    c = concert(slug)
    song(c, name)
    if any(j["proc"].poll() is None for j in JOBS.values()):
        raise HTTPException(409, "已有一首在重跑，等它跑完")
    log = c.logs / f"{time.strftime('%Y%m%d-%H%M%S')}_rerun_{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = log.open("w")
    proc = subprocess.Popen([str(VENV_PY), "-m", "workflow_v2", "run", slug, "--from", "refine", "--to", "refine",
                             "--songs", name], cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
    JOBS[(slug, name)] = {"proc": proc, "started": time.strftime("%H:%M:%S"), "log": log}
    return job_state(c, name)


MEDIA_OK = {".mp4", ".ass", ".jpg", ".srt"}


@app.get("/media/{slug}/{path:path}")
def media(slug: str, path: str):
    c = concert(slug)
    f = (c.dir / path)
    parts = Path(path).parts
    allowed = f.suffix in MEDIA_OK and (
        path == "source.mp4"
        or (len(parts) == 3 and parts[0] == "songs" and parts[2] in ("lyrics.ass", "preview.mp4"))
        or (len(parts) == 4 and parts[0] == "songs" and parts[2] == "exp" and parts[3] == "lyrics.ass")
        or (len(parts) >= 4 and parts[0] == "songs" and parts[2] in ("covers", "post")))
    if not allowed or ".." in parts or not f.resolve().is_file():
        raise HTTPException(404)
    return FileResponse(f)  # source.mp4 是软链接时也照样给；Range 请求由 FileResponse 处理


class NoCacheStatic(StaticFiles):
    """前端没有构建和文件指纹：每次回源校验，改了 JS/CSS 刷新就生效。"""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStatic(directory=ROOT / "web_v2", html=True), name="web")
