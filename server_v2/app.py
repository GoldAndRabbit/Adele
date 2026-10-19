# -*- coding: utf-8 -*-
"""v2 审核页：场次 / 单曲 API + 静态前端（web_v2/，纯 JS，前端结构拷自 SubDub）。

    .venv/bin/python -m workflow_v2 serve        # → http://127.0.0.1:8160

和 SubDub 只读后台不同，这里有三个写操作，都只写 concerts/<slug>/ 下的 JSON、不碰视频：
  POST .../review    保存选中的封面、标题、介绍、标签、备注、审核状态（review.json）
  POST .../segment   人工调整这首的起止（segments.json，manual=true；之后要重跑 refine）
  POST .../rerun     后台重跑这一首的 refine（边界改过之后），一次只跑一个
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
        "thumb": media_url(c, it["name"], (chosen or covers[0])["file"]) if covers else None,
        "job": job_state(c, it["name"]),
    }


def exp_data(d, sub, ass_url):
    """一份实验结果（exp/ 或 exp_v2/）给审核页：逐句表格 + 字幕文件 + 用的模型。"""
    x = d / sub
    if not (x / "lines.json").exists():
        return None
    from workflow_v2 import align3
    from workflow_v2.align4 import line_lang
    import qwen_asr
    prof = read_json(x / "profile.json", {}) or {}
    main = prof.get("main") or "en"
    xl = ass_lines(x / "lyrics.ass") if (x / "lyrics.ass").exists() else []
    xrows = []
    for r in read_json(x / "lines.json", []) or []:
        t = (r["start_ms"] or 0) / 1000
        m = next((y for y in xl if abs(y["start"] - t) < 0.06 and y["orig"] == r["text"]), None) if r["text"] else None
        lang = r.get("lang") or line_lang(r.get("text") or r.get("genius") or r.get("qwen") or "", main)
        xrows.append({**r, "lang": lang, "zh": m["zh"] if m else "", "start": t, "end": (r["end_ms"] or 0) / 1000})
    have = {(round(r["start"], 1), r["text"]) for r in xrows}
    xl = [y for y in xl if y["style"] != "Note"]   # 顶部注释不是字幕行（逐句表格里挂在对应那句下面）
    for y in xl:   # 片头歌名（翻译时加的）和讲话：字幕文件里有、逐句数据里没有的
        if y["orig"].startswith("《") or (y["style"] != "Default" and (round(y["start"], 1), y["orig"]) not in have):
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
    # 歌曲中间的水印（workflow_v3/watermark.py）也作为一行插进表格，方便对照时间和位置
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
    for sg in cr.get("segments", []):
        ev = sg.get("evidence", {})
        lines_ = [f"{k}：{'✓' if v.get('成立') else '✗'}  {v.get('说明', '')}；值 = {json.dumps(v.get('值'), ensure_ascii=False)[:120]}"
                  for k, v in ev.items()]
        xrows.append({"start_ms": round(sg["s"] * 1000), "end_ms": round(sg["e"] * 1000), "start": sg["s"], "end": sg["e"],
                      "genius": "", "qwen": sg.get("heard", "")[:80], "lang": "", "zh": "", "removed": False, "crowdseg": True,
                      "text": f"观众合唱检测：{sg['verdict']}（置信度 {sg['confidence']}）· 该唱 {len(sg.get('want', []))} 句",
                      "verdict": "crowdseg", "style": "crowdseg", "strategy": "\n".join(lines_)})
    xrows.sort(key=lambda r: (r["start_ms"] is None, r["start_ms"] or 0))
    # 翻译（song_translation_workflow：translation/result.json；旧的二次翻译 zh2.json 兼容）：按时间 + 原文对回每一行
    tr = read_json(x / "translation" / "result.json", {}) or {}
    z2 = read_json(x / "zh2.json", {}) or {}
    model = tr.get("model") or z2.get("model")
    if tr.get("units"):
        notes = {int(k): v for k, v in (tr.get("final_notes") or tr.get("notes") or {}).items()}
        for r in xrows:
            # 原文比较前统一空白（日文歌词里有全角空格，字幕文件里是半角）
            rt = re.sub(r"\s+", " ", r["text"] or "").strip()
            m = next((u for u in tr["units"] if abs(u["start"] - (r["start_ms"] or 0)) < 60 and u["orig"] == rt), None)
            if m:
                r.update({"zh": m.get("v1", r.get("zh", "")), "zh2": m.get("v2_final", m.get("v2", "")), "zh_issues": m.get("issues", []),
                          "zh_locked": m.get("locked", False), "unit": m["i"], "note": notes.get(m["i"], "")})
                if m.get("dropped"):   # 幻听：不出字幕，表格里也不显示翻译
                    r.update({"removed": True, "verdict": "unconfirmed", "strategy": m["dropped"], "zh": "", "zh2": "", "note": ""})
    elif z2.get("items"):
        for r in xrows:
            m = next((it for it in z2["items"] if abs(it["start_ms"] - (r["start_ms"] or 0)) < 60 and it["orig"] == r["text"]), None)
            if m:
                r["zh2"] = m["zh2"]
    zh2_ass = ass_url.replace("lyrics.ass", "lyrics_zh2.ass") if (x / "lyrics_zh2.ass").exists() else None
    brief = tr.get("brief") or {}
    return {"rows": xrows, "ass": ass_url if (x / "lyrics.ass").exists() else None, "ass_zh2": zh2_ass,
            "zh2_model": model, "profile": prof or None, "editable_zh": bool(tr.get("units")),
            "brief": {k: brief.get(k) for k in ("theme", "voice", "tone", "core_lines", "notes")} if brief else None,
            "models": {"asr": align3.MODEL, "verify": qwen_asr.MODEL}}


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
    # v3（exp_v3/，workflow_v3）和 v2（exp_v2/，align4.py）：审核页默认看 v3，可以切到 v2 对比；v1、v0 不再显示
    exps = {k: exp_data(d, sub, f"/media/{slug}/songs/{name}/{sub}/lyrics.ass") for k, sub in (("v4", "exp_v4"), ("v3", "exp_v3"), ("v2", "exp_v2"))}
    exps = {k: v for k, v in exps.items() if v}
    from workflow_v2.align4 import line_lang
    main = info.get("lang") or "en"
    for r in rows:
        r.setdefault("lang", line_lang(r.get("text") or r.get("genius") or "", main) if (r.get("text") or r.get("genius")) else "")
    return {
        **base,
        "exps": exps,
        "artist": it.get("artist"), "parts": it.get("parts"), "lang": info.get("lang"),
        "genius_urls": info.get("genius_urls", []), "slice": info.get("slice"),
        "lyric_start": segs.get(name, {}).get("lyric_start"), "lyric_end": segs.get(name, {}).get("lyric_end"),
        "ass": f"/media/{slug}/songs/{name}/lyrics.ass" if (d / "lyrics.ass").exists() else None,
        "preview": f"/media/{slug}/songs/{name}/preview.mp4" if (d / "preview.mp4").exists() else None,
        "preview_span": info.get("preview"), "align": info.get("align"),
        "lines": lines,
        "rows": rows,
        "covers": [{**x, "file": media_url(c, name, x["file"]),
                    "file_4x3": media_url(c, name, x["file_4x3"]) if x["file_4x3"] else None}
                   for x in cover_candidates(d)],
        "draft": read_json(d / "post_draft.json", {}),
        # 歌曲中间的半透明 logo 水印计划（workflow_v3/watermark.py），审核页只做预览，不改视频
        "watermark": read_json(d / "watermark.json", None),
        "review_entry": rv["songs"].get(name, {}),
    }


def v3_dirs(slug, name):
    """v3 结果的真实目录（v1 单曲在 concerts/v1_singles 里是软链接，定稿表要写到 posts/<name>/）。"""
    c = concert(slug)
    d = c.song_dir(song(c, name))
    x = (d / "exp_v3").resolve()   # 审核页不再编辑；这个接口只给 v3 用
    if not (x / "translation" / "result.json").exists():
        raise HTTPException(400, "这首还没有 v3 翻译")
    return x.parent, x


@app.post("/api/concerts/{slug}/songs/{name}/zh")
def post_zh(slug: str, name: str, body: dict = Body(...)):
    """审核页直接改中文（v2）：存进这首歌的定稿表 zh_fixed.json（只这首），重新生成字幕文件（不重新调用模型）。
    zh 为空字符串 = 取消定稿，恢复模型的译法。"""
    from workflow_v3.song_translation_workflow import build_outputs
    d, x = v3_dirs(slug, name)
    orig, zh = (body.get("orig") or "").strip(), (body.get("zh") or "").strip()
    if not orig:
        raise HTTPException(400, "缺少原文")
    f = d / "zh_fixed.json"
    fixed = json.loads(f.read_text()) if f.exists() else {}
    if zh:
        fixed[orig] = zh
    else:
        fixed.pop(orig, None)
    f.write_text(json.dumps(fixed, ensure_ascii=False, indent=1))
    build_outputs(d, x)
    return {"ok": True, "fixed": len(fixed)}


@app.post("/api/concerts/{slug}/songs/{name}/note")
def post_note(slug: str, name: str, body: dict = Body(...)):
    """审核页改 / 删 / 加顶部注释：{orig: 原文, note: "注：…"}，note 为空 = 删掉；存进这首的 zh_notes.json（按原文）。"""
    from workflow_v3.song_translation_workflow import build_outputs
    d, x = v3_dirs(slug, name)
    f = d / "zh_notes.json"
    notes = json.loads(f.read_text()) if f.exists() else {}
    notes[(body.get("orig") or "").strip()] = (body.get("note") or "").strip()
    f.write_text(json.dumps(notes, ensure_ascii=False, indent=1))
    build_outputs(d, x)
    return {"ok": True}


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


def media_url(c, name, rel):
    """封面会原地重新生成（文件名不变）：地址带上修改时间，换了图浏览器一定重新拉，不会用缓存里的旧图。"""
    f = c.song_dir({"name": name}) / rel
    v = int(f.stat().st_mtime) if f.exists() else 0
    return f"/media/{c.slug}/songs/{name}/{rel}?v={v}"


@app.get("/media/{slug}/{path:path}")
def media(slug: str, path: str):
    c = concert(slug)
    f = (c.dir / path)
    parts = Path(path).parts
    allowed = f.suffix in MEDIA_OK and (
        path == "source.mp4"
        or (len(parts) == 3 and parts[0] == "songs" and parts[2] in ("lyrics.ass", "preview.mp4"))
        or (len(parts) == 4 and parts[0] == "songs" and parts[2] in ("exp", "exp_v2", "exp_v3", "exp_v4") and parts[3] in ("lyrics.ass", "lyrics_zh2.ass"))
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


app.mount("/", NoCacheStatic(directory=ROOT / "web_v2", html=True), name="web")
