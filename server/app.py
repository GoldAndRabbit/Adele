# -*- coding: utf-8 -*-
"""审核页后端：场次 / 单曲 API + 静态前端（web/，纯 JS，前端结构拷自 SubDub）。

    .venv/bin/python -m workflow.live serve        # → http://127.0.0.1:8160

页面只展示（字幕、翻译的修改都通过对话改定稿表）；写操作只有这几个，都不碰视频：
  POST .../review          保存选中的封面、标题、介绍、标签、备注、审核状态（concerts/<slug>/review.json）
  POST .../cover_download  选中的封面存成 PNG 放进这首的 post/
  POST .../reveal_final    在 Finder 里定位这首的成品
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from workflow.live import review  # noqa: E402
from workflow.live.package import cover_candidates  # noqa: E402
from workflow.letterbox import content_box  # noqa: E402
from workflow.live.paths import CONCERTS, Concert, read_json  # noqa: E402

app = FastAPI(title="adele review")


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
        "thumb": media_url(c, it["name"], (chosen or covers[0])["file"]) if covers else None,
    }


def exp_data(d, ass_url):
    """字幕结果（subs/）给审核页：逐句表格 + 字幕文件 + 用的模型。"""
    x = d / "subs"
    if not (x / "lines.json").exists():
        return None
    from workflow.live import asr_match
    from workflow.live.line_match import line_lang
    prof = read_json(x / "profile.json", {}) or {}
    main = prof.get("main") or "en"
    xl = ass_lines(x / "lyrics.ass") if (x / "lyrics.ass").exists() else []
    xrows = []
    for r in read_json(x / "lines.json", []) or []:
        t = (r["start_ms"] or 0) / 1000
        m = next((y for y in xl if abs(y["start"] - t) < 0.06 and y["orig"] == r["text"]), None) if r["text"] else None
        lang = r.get("lang") or line_lang(r.get("text") or r.get("genius") or r.get("qwen") or "", main)
        xrows.append({**r, "lang": lang, "zh": m["zh"] if m else "", "start": t, "end": (r["end_ms"] or 0) / 1000})
    have = lambda y: any(abs(r["start"] - y["start"]) < 0.15 and r["text"] == y["orig"] for r in xrows)   # 2.946 / 2.950 是同一句
    xl = [y for y in xl if y["style"] != "Note"]   # 顶部注释不是字幕行（逐句表格里挂在对应那句下面）
    for y in xl:   # 片头歌名（翻译时加的）和讲话：字幕文件里有、逐句数据里没有的
        if y["orig"].startswith("《") or (y["style"] != "Default" and not have(y)):
            xrows.append({"start_ms": round(y["start"] * 1000), "end_ms": round(y["end"] * 1000), "start": y["start"],
                          "end": y["end"], "genius": "", "qwen": "", "heard": "", "text": y["orig"], "zh": y["zh"],
                          "lang": "" if y["orig"].startswith("《") else line_lang(y["orig"], main),
                          "verdict": "title", "removed": False, "speech": y["style"] != "Default",
                          "style": "title" if y["orig"].startswith("《") else None, "credit": y.get("extra", ""),
                          "strategy": "片头歌名（歌名翻译）" if y["orig"].startswith("《") else "讲话"})
        elif y["style"] != "Default":   # 讲话行：逐句数据里有，补上中文
            for r in xrows:
                if r["text"] == y["orig"] and abs(r["start"] - y["start"]) < 0.06:
                    r["zh"], r["speech"] = y["zh"], True
    # 歌曲中间的水印（workflow/song/watermark.py）也作为一行插进表格，方便对照时间和位置
    wm = read_json(d / "watermark.json", None) or {}
    for it in wm.get("items", []):
        where = ("左" if it["x"] < 0.2 else "右" if it["x"] > 0.6 else "中") + ("上" if it["y"] < 0.25 else "中" if it["y"] < 0.6 else "下")
        xrows.append({"start_ms": round(it["t"] * 1000), "end_ms": round((it["t"] + it["dur"]) * 1000), "start": it["t"],
                      "end": it["t"] + it["dur"], "genius": "", "qwen": "", "text": f"朝阳 Adele 水印：{where}，{it['dur']:.0f} 秒，"
                      f"透明度 {wm.get('opacity', 0.6):.0%}", "zh": "", "lang": "", "verdict": "wm", "removed": False,
                      "style": "wm", "watermark": True,
                      "strategy": f"位置 x={it['x']:.2f} y={it['y']:.2f}（占画面比例），淡入淡出各 {it['fade']} 秒；避开字幕区、左上角 logo 和人脸（这一刻检测到 {it.get('faces', 0)} 张脸）"})
    # 观众合唱检测（song_crowd_workflow）：每个候选段一行，鼠标停上去看每项证据
    cr = read_json(x / "crowd.json", None) or {}
    # 检测行里列出这一段排进去的合唱字幕
    seg_rows = lambda f, a, b, cond: [{"start": r["start_ms"] / 1000, "text": r.get("text")} for r in (read_json(f, []) or [])
                                      if a - 0.2 <= r["start_ms"] / 1000 < b and (r.get("text") or "").strip() and cond(r)]
    for sg in cr.get("segments", []):
        ev = sg.get("evidence", {})
        lines_ = [f"{k}：{'✓' if v.get('成立') else '✗'}  {v.get('说明', '')}；值 = {json.dumps(v.get('值'), ensure_ascii=False)[:120]}"
                  for k, v in ev.items()]
        xrows.append({"start_ms": round(sg["s"] * 1000), "end_ms": round(sg["e"] * 1000), "start": sg["s"], "end": sg["e"],
                      "genius": "", "qwen": sg.get("heard", "")[:80], "lang": "", "zh": "", "removed": False, "crowdseg": True,
                      "text": f"观众合唱检测：{sg['verdict']}（置信度 {sg['confidence']}）· 该唱 {len(sg.get('want', []))} 句",
                      "verdict": "crowdseg", "style": "crowdseg", "strategy": "\n".join(lines_),
                      "crowd_lines": seg_rows(x / "lines.json", sg["s"], sg["e"], lambda r: r.get("verdict") == "crowd")})
    xrows.sort(key=lambda r: (r["start_ms"] is None, r["start_ms"] or 0))
    # 翻译（song_translation_workflow：translation/result.json）：按时间 + 原文对回每一行
    tr = read_json(x / "translation" / "result.json", {}) or {}
    if tr.get("units"):
        notes = {int(k): v for k, v in (tr.get("final_notes") or tr.get("notes") or {}).items()}
        for r in xrows:
            # 原文比较前统一空白（日文歌词里有全角空格，字幕文件里是半角）
            rt = re.sub(r"\s+", " ", r["text"] or "").strip()
            m = next((u for u in tr["units"] if abs(u["start"] - (r["start_ms"] or 0)) < 60 and u["orig"] == rt), None)
            if m:
                r.update({"zh": m.get("v1", r.get("zh", "")), "zh2": m.get("v2_final", m.get("v2", "")), "zh_issues": m.get("issues", []),
                          "zh_locked": m.get("locked", False), "unit": m["i"], "note": notes.get(m["i"], ""),
                          "zh3": m.get("v3_final", "")})
                if m.get("dropped"):   # 幻听：不出字幕，表格里也不显示翻译
                    r.update({"removed": True, "verdict": "unconfirmed", "strategy": m["dropped"], "zh": "", "zh2": "", "note": ""})
    zh2_ass = ass_url.replace("lyrics.ass", "lyrics_literal.ass") if (x / "lyrics_literal.ass").exists() else None
    zh3_ass = ass_url.replace("lyrics.ass", "lyrics_poetic.ass") if (x / "lyrics_poetic.ass").exists() else None   # 诗意版
    return {"rows": xrows, "ass": ass_url if (x / "lyrics.ass").exists() else None, "ass_literal": zh2_ass, "ass_poetic": zh3_ass,
            "zh3_model": tr.get("poetic_model"), "zh2_model": tr.get("model"), "profile": prof or None,
            "models": {"asr": asr_match.MODEL}}


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
                    "orig": clean[0] if clean else "", "zh": clean[1] if len(clean) > 1 else "",
                    "extra": " ".join(clean[2:])})   # 片头第三行：AI 精校署名
    return out


@app.get("/api/concerts/{slug}/songs/{name}")
def get_song(slug: str, name: str):
    c = concert(slug)
    it = song(c, name)
    d = c.song_dir(it)
    segs = {s["name"]: s for s in (c.load("segments") or {}).get("items", [])}
    rv = review.load(c)
    base = song_summary(c, it, segs, rv)
    info = read_json(d / "song.json", {})
    return {
        **base,
        "exp": exp_data(d, f"/media/{slug}/songs/{name}/subs/lyrics.ass"),
        "artist": it.get("artist"), "genius_urls": info.get("genius_urls", []), "slice": info.get("slice"),
        "preview": f"/media/{slug}/songs/{name}/preview.mp4" if (d / "preview.mp4").exists() else None,
        "preview_span": info.get("preview"),
        # 成品（workflow/song/render.py）：4K60、烧好字幕和水印、FLAC；出来了审核页预览下方直接播
        "final": (media_url(c, name, f"post/{name} 4K60FPS Sub-WaterMark.mp4").replace(" ", "%20")
                  if (d / "post" / f"{name} 4K60FPS Sub-WaterMark.mp4").exists() else None),
        "final_path": str((d / "post" / f"{name} 4K60FPS Sub-WaterMark.mp4").resolve()),
        # 成品目录里所有成品（正式成品 + 对比用的其他编码版本），审核页每个一个播放器
        "finals": finals(c, name, d),
        "covers": [{**x, "file": media_url(c, name, x["file"]),
                    "file_4x3": media_url(c, name, x["file_4x3"]) if x["file_4x3"] else None}
                   for x in cover_candidates(d)],
        "draft": read_json(d / "post_draft.json", {}),
        # B 站投稿 JSON（post_bili/upload.py 生成，上传时原样提交），审核页只展示
        "bili_upload": (d / "post" / "bili_upload.json").read_text() if (d / "post" / "bili_upload.json").exists() else None,
        "bili_upload_path": str((d / "post" / "bili_upload.json").resolve()),
        # 歌曲中间的半透明 logo 水印计划（workflow/song/watermark.py），审核页只做预览，不改视频
        "watermark": read_json(d / "watermark.json", None),
        # 画面内容区域（去掉宽银幕的上下黑边）：左上角 logo、水印都相对它放
        "box": content_box(d),
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


@app.post("/api/concerts/{slug}/songs/{name}/cover_download")
def post_cover_download(slug: str, name: str, body: dict = Body(...)):
    """候选封面「下载」：16:9 和 4:3 两张存成 PNG，放到这首歌成品视频所在的 post/ 目录：
    post/<歌>_cover_picked_<日时分>.png、post/<歌>_cover_picked_4x3_<日时分>.png。
    单曲的 covers 是软链接到 posts/<歌>/covers，成品在 posts/<歌>/post/，顺着软链接找。"""
    from PIL import Image
    c = concert(slug)
    it = song(c, name)
    cid = body.get("id") or ""
    if not re.fullmatch(r"(closeup|half|full|scene|cover)_\d\d", cid):
        raise HTTPException(400, "封面 id 不对")
    covers = (c.song_dir(it) / "covers").resolve()
    # 演唱会：<歌>/covers；单曲：<歌>/post/cover（make_cover 默认）；早期：<歌>/exp/covers
    base = covers.parent.parent if covers.parent.name in ("exp", "post") else covers.parent
    post = base / "post"
    post.mkdir(exist_ok=True)
    stamp = time.strftime("%d%H%M")
    saved = []
    for src, suffix in ((covers / f"{cid}.jpg", ""), (covers / f"{cid}_4x3.jpg", "_4x3")):
        if not src.exists():
            continue
        dst = post / f"{name}_cover_picked{suffix}_{stamp}.png"
        Image.open(src).convert("RGB").save(dst)
        saved.append(str(dst.relative_to(ROOT)))
    if not saved:
        raise HTTPException(404, "没有这张封面")
    return {"saved": saved}


MEDIA_OK = {".mp4", ".ass", ".jpg"}


FINAL_LABELS = {"hw_videotoolbox": "硬件编码 H.264 VideoToolbox（对比版）", "hevc_videotoolbox": "硬件编码 HEVC VideoToolbox（对比版）"}


def finals(c, name, d):
    main = f"{name} 4K60FPS Sub-WaterMark.mp4"
    files = sorted((d / "post").glob("*.mp4"), key=lambda f: (f.name != main, f.name))
    out = []
    for f in files:
        if ".partial." in f.name:
            continue
        label = "软件编码 libx264（正式成品）" if f.name == main else \
            next((v for k, v in FINAL_LABELS.items() if k in f.name), f.name)
        out.append({"label": label, "file": f.name, "url": media_url(c, name, f"post/{f.name}").replace(" ", "%20"),
                    "path": str(f.resolve()), "gb": round(f.stat().st_size / 1e9, 2)})
    return out


def media_url(c, name, rel):
    """封面会原地重新生成（文件名不变）：地址带上修改时间，换了图浏览器一定重新拉，不会用缓存里的旧图。"""
    f = c.song_dir({"name": name}) / rel
    v = int(f.stat().st_mtime) if f.exists() else 0
    return f"/media/{c.slug}/songs/{name}/{rel}?v={v}"


@app.post("/api/concerts/{slug}/songs/{name}/reveal_final")
def reveal_final(slug: str, name: str, file: str = ""):
    """在 Finder 里定位这首的成品（只开这一个文件，审核页「在 Finder 中显示」用）；file：成品目录里的哪个文件，默认正式成品。"""
    c = concert(slug)
    post = c.song_dir(song(c, name)) / "post"
    f = (post / (file or f"{name} 4K60FPS Sub-WaterMark.mp4")).resolve()
    if f.parent != post.resolve() or f.suffix != ".mp4" or not f.is_file():
        raise HTTPException(404)
    subprocess.run(["open", "-R", str(f)], check=False)
    return {"ok": True}


@app.get("/media/{slug}/{path:path}")
def media(slug: str, path: str):
    c = concert(slug)
    f = (c.dir / path)
    parts = Path(path).parts
    allowed = f.suffix in MEDIA_OK and (
        path == "source.mp4"
        or (len(parts) == 3 and parts[0] == "songs" and parts[2] == "preview.mp4")
        or (len(parts) == 4 and parts[0] == "songs" and parts[2] == "subs" and parts[3] in ("lyrics.ass", "lyrics_literal.ass", "lyrics_poetic.ass"))
        or (len(parts) >= 4 and parts[0] == "songs" and parts[2] in ("covers", "post")))
    if not allowed or ".." in parts or not f.resolve().is_file():
        raise HTTPException(404)
    # 封面 / 字幕会原地重新生成（文件名不变）：每次回源校验（ETag 没变就 304），不然浏览器按启发式缓存一直显示旧图
    return FileResponse(f, headers={"Cache-Control": "no-cache"})  # source.mp4 是软链接时也照样给；Range 请求由 FileResponse 处理


class NoCacheStatic(StaticFiles):
    """前端没有构建和文件指纹：每次回源校验，改了 JS/CSS 刷新就生效。"""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStatic(directory=ROOT / "web", html=True), name="web")
