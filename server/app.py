# -*- coding: utf-8 -*-
"""审核页后端：场次 / 单曲 API + 静态前端（web/，纯 JS，前端结构拷自 SubDub）。

    .venv/bin/python -m workflow.live serve        # → http://127.0.0.1:8160

页面只展示（字幕、翻译的修改都通过对话改定稿表）；写操作只有这几个，都不碰视频：
  POST .../review          保存选中的封面、标题、介绍、标签、备注、审核状态（concerts/<slug>/review.json）
  POST .../cover_download  选中的封面存成 PNG 放进这首的 post/
  POST .../reveal_final    在 Finder 里定位这首的成品
"""

import hashlib
import json
import tempfile
import re
import shutil
from fractions import Fraction
from functools import lru_cache
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Lock, Semaphore, Thread

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from workflow.vertical_post import posting_inputs, caption as vertical_post_caption, cover_attachment, replace_cover_selection, submission, SHANGHAI
from workflow.subtitle_spelling import display_english
from workflow.live import review  # noqa: E402
from workflow.live.package import compact_cover_title, cover_candidates  # noqa: E402
from workflow.letterbox import content_box, logo_corner  # noqa: E402
from workflow.live.paths import CONCERTS, Concert, write_json  # noqa: E402
from server.metadata import read_json  # noqa: E402
from server.library_order import track_dates  # noqa: E402
from workflow.delivery_config import products_ready, render_platforms  # noqa: E402
from workflow.live.singles import production_day  # noqa: E402

from server.selection_preview import router as selection_preview_router

app = FastAPI(title="adele review")
app.include_router(selection_preview_router)


def concert_display_title(info, slug, *, year_first=False):
    title = info.get("title") or slug
    date = str(info.get("date") or "")
    if not re.match(r"^\d{4}(?:-|$)", date):
        return title
    year = date[:4]
    edition = re.search(r"第\s*(\d+)\s*届", title)
    if slug.startswith("grammys_") and edition:
        return f"{year}-格莱美-第{edition[1]}届"
    artist = (info.get("artist") or "").strip()
    event = re.sub(rf"^{year}年?\s*|\s*{year}年?$", "", title).strip()
    if artist:
        event = re.sub(rf"^{re.escape(artist)}\s*[-–—]\s*", "", event, flags=re.I)
    parts = (year, artist, event) if year_first else (artist, year, event)
    return "-".join(filter(None, parts))


def single_artist(it):
    return (it.get("artist") or "").strip() or "未知歌手"


def artist_slug(artist):
    return "artist_" + artist.casefold().encode("utf-8").hex()


HALFTIME_SLUG = "super_bowl_halftime"
HALFTIME_TITLE = "历届超级碗中场秀"


GROUP_ARTIST_ALIASES = {"Giovanni Zarrella & Ricchi e Poveri": "Ricchi e Poveri"}


def group_artist(it):
    artist = single_artist(it)
    return GROUP_ARTIST_ALIASES.get(artist, artist)


def single_group(it):
    event = " ".join(it.get(key) or "" for key in ("display_title", "title", "notes"))
    if "超级碗中场秀" in event or re.search(r"super bowl.*half[ -]?time", event, re.I):
        return HALFTIME_SLUG
    return artist_slug(group_artist(it))


def concert(slug):
    dated = re.fullmatch(r"singles_(\d{6})", slug)
    single_collection = slug.startswith("artist_") or slug == HALFTIME_SLUG
    c = Concert("singles" if dated or single_collection else slug)
    if not c.info.exists() or c.dir.parent != CONCERTS:
        raise HTTPException(404, "没有这个场次")
    if dated:
        c.review_day = dated[1]
    if single_collection:
        c.single_collection = slug
    return c


def visible_items(c):
    day = getattr(c, "review_day", None)
    return [it for it in c.items() if not it.get("review_hidden") and (not day or production_day(it) == day)
            and (not getattr(c, "single_collection", None) or single_group(it) == c.single_collection)]


def display_title(it):
    return it.get("display_title") or it["title"]


def song(c, name):
    try:
        it = c.item(name)
    except KeyError:
        raise HTTPException(404, "没有这首歌")
    if it["kind"] != "song":
        raise HTTPException(400, "过场不审核")
    return it


def has_picked_cover(d):
    return any((d / "post").glob("*_cover_picked_*.png"))


def saved_cover_id(d, candidates):
    from PIL import Image, ImageChops
    picks = (f for f in (d / "post").glob("*_cover_picked_*.png") if "_4x3_" not in f.name)
    latest = max(picks, key=lambda f: f.stat().st_mtime, default=None)
    if not latest:
        return None
    try:
        with Image.open(latest) as src:
            picked = src.convert("RGB")
        for candidate in candidates:
            with Image.open(d / candidate["file"]) as src:
                if src.size == picked.size and not ImageChops.difference(picked, src.convert("RGB")).getbbox():
                    return candidate["id"]
    except OSError:
        pass
    return None


def selected_portrait_cover(directory):
    folder = directory / "vertical"
    selected = read_json(folder / "selected.json", {}).get("cover")
    if selected and any(r["file"] == selected for r in read_json(folder / "candidates.json", [])):
        return selected if (folder / selected).is_file() else None
    return None


def portrait_release(d, *, current_only=True):
    from workflow.vertical_workflow import revision
    folder = d / "vertical"
    record = read_json(folder / "release.json", {})
    if record.get("file") and (folder / record["file"]).is_file() and (not current_only or record.get("revision") == revision(d)):
        return record
    return None


def song_summary(c, it, segs, rv):
    d = c.song_dir(it)
    seg = segs.get(it["name"], {})
    source_info = read_json(d / "song.json", {})
    if source_info.get("source_file") and source_info.get("slice"):
        seg = {**seg, "start": source_info["slice"][0], "end": source_info["slice"][1]}
    st = review.song_status(c, it)
    draft = read_json(d / "post_draft.json", {})
    posting_draft, concert_name, artist_zh = posting_inputs(c, it, draft)
    caption = vertical_post_caption(posting_draft, concert_name, artist_zh)
    entry = rv["songs"].get(it["name"], {})
    covers = cover_candidates(d)
    chosen = next((x for x in covers if x["id"] == entry.get("cover")), None)
    selected = selected_portrait_cover(d)
    attachment = cover_attachment(d, selected)
    return {
        "idx": it["idx"], "name": it["name"], "title": display_title(it), "notes": it.get("notes"), "artist": it.get("artist"),
        "fps": source_info.get("fps") or read_json(c.info, {}).get("fps"),
        "start": seg.get("start"), "end": seg.get("end"), "confidence": seg.get("confidence"),
        "flags": seg.get("flags", []), "manual": bool(seg.get("manual")),
        "stage": st["stage"], "review": st["review"], "needs_refine": st["needs_refine"],
        "post_ready": bool(caption and attachment), "douyin_caption": caption,
        "douyin_submission": submission(posting_draft, concert_name, artist_zh),
        "subtitles_ready": (d / "subs/lyrics.ass").is_file() and (d / "subs/lyrics.ass").stat().st_size > 0,
        "portrait_release_ready": bool(portrait_release(d)),
        "dual_products_ready": dual_products_ready(d),
        "platform_covers_ready": platform_covers_ready(d),
        "portrait_cover_selected": bool(selected),
        "cover_selected": bool(entry.get("cover")) or has_picked_cover(d),
        "thumb": media_url(c, it["name"], (chosen or covers[0])["file"]) if covers else None,
    }


def exp_data(d, ass_url):
    """字幕结果（subs/）给审核页：逐句表格 + 字幕文件 + 用的模型。"""
    x = d / "subs"
    from workflow.live import asr_match
    from workflow.live.line_match import line_lang
    prof = read_json(x / "profile.json", {}) or {}
    main = prof.get("main") or "en"
    xl = ass_lines(x / "lyrics.ass") if (x / "lyrics.ass").exists() else []
    if not (x / "lines.json").exists() and not any(row["style"] == "Note" for row in xl):
        return None
    xrows = []
    for r in read_json(x / "lines.json", []) or []:
        t = (r["start_ms"] or 0) / 1000
        m = next((y for y in xl if abs(y["start"] - t) < 0.06 and display_english(y["orig"]) == display_english(r["text"])), None) if r["text"] else None
        lang = r.get("lang") or line_lang(r.get("text") or r.get("genius") or r.get("qwen") or "", main)
        xrows.append({**r, "lang": lang, "zh": m["zh"] if m else "", "start": t, "end": (r["end_ms"] or 0) / 1000})
    have = lambda y: any(abs(r["start"] - y["start"]) < 0.15 and display_english(r["text"] or "") == display_english(y["orig"]) for r in xrows)   # 2.946 / 2.950 是同一句
    note_events = [y for y in xl if y["style"] == "Note"]
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
                if display_english(r["text"] or "") == display_english(y["orig"]) and abs(r["start"] - y["start"]) < 0.06:
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
        notes = {int(k): v for k, v in tr.get("final_notes", tr.get("notes") or {}).items()}
        for r in xrows:
            # 原文比较前统一空白（日文歌词里有全角空格，字幕文件里是半角）
            rt = display_english(re.sub(r"\s+", " ", r["text"] or "").strip())
            m = next((u for u in tr["units"] if abs(u["start"] - (r["start_ms"] or 0)) < 60 and display_english(re.sub(r"\s+", " ", u["orig"]).strip()) == rt), None)
            if m:
                r.update({"zh": m.get("v1", r.get("zh", "")), "zh2": m.get("v2_final", m.get("v2", "")), "zh_issues": m.get("issues", []),
                          "zh_locked": m.get("locked", False), "unit": m["i"], "note": notes.get(m["i"], ""),
                          "zh3": m.get("v3_final", "")})
                if m.get("dropped"):   # 幻听：不出字幕，表格里也不显示翻译
                    r.update({"removed": True, "verdict": "unconfirmed", "strategy": m["dropped"], "zh": "", "zh2": "", "note": ""})
    # Instrumental notes and legacy cues may have no matching ASR row.
    for cue in note_events:
        text = cue["orig"]
        if not any(r.get("note") == text and abs(r["start"] - cue["start"]) < .06 for r in xrows):
            xrows.append({"start": cue["start"], "end": cue["end"], "start_ms": round(cue["start"] * 1000),
                          "end_ms": round(cue["end"] * 1000), "text": "音乐注释", "note": text,
                          "verdict": "note", "style": "Note", "removed": False})
    xrows.sort(key=lambda row: (row["start_ms"] is None, row["start_ms"] or 0))
    zh2_ass = ass_url.replace("lyrics.ass", "lyrics_literal.ass") if (x / "lyrics_literal.ass").exists() else None
    zh3_ass = ass_url.replace("lyrics.ass", "lyrics_poetic.ass") if (x / "lyrics_poetic.ass").exists() else None   # 诗意版
    for row in xrows:
        row["text"] = display_english(row["text"] or "")
    return {"rows": xrows, "ass": ass_url if (x / "lyrics.ass").exists() else None, "ass_literal": zh2_ass, "ass_poetic": zh3_ass,
            "zh3_model": tr.get("poetic_model"), "zh2_model": tr.get("model"), "profile": prof or None,
            "models": {"asr": asr_match.MODEL}}


def platform_covers_ready(directory):
    ai = directory / "covers" / "ai"
    local = {m["file"] for m in read_json(ai / "masters.json", [])
             if m.get("file")}
    if not local:
        return False
    required = {("bili-ai", "16x9"), ("bili-ai", "4x3"), ("douyin-ai", "3x4"), ("douyin-ai", "4x3")}
    by_master = {}
    for row in read_json(ai / "variants.json", []):
        master = row.get("master")
        version = (row.get("platform"), row.get("ratio"))
        if master in local and version in required and row.get("file") and (ai / row["file"]).is_file():
            by_master.setdefault(master, set()).add(version)
    return any(versions == required for versions in by_master.values())


def dual_products_ready(directory):
    # Keep the API field name for existing clients; its required outputs follow
    # the production default, including Bilibili-only deliveries.
    return products_ready(directory)


@app.get("/api/product-progress")
def product_progress():
    """Read delivered song products independently of the cached review-material index."""
    ready = {}
    for concert in CONCERTS.iterdir():
        songs = concert / "songs"
        if songs.is_dir():
            ready[concert.name] = [song.name for song in songs.iterdir() if dual_products_ready(song)]
    return ready


class ReviewSnapshot:
    """Serve the last successful disk scan while one worker refreshes it."""
    def __init__(self, key):
        self.path = Path.home() / "Library/Caches/adele-review/index-v1" / (key + ".json")
        self.lock = Lock()
        self.refresh_lock = Lock()
        try:
            self.value = read_json(self.path)
        except (OSError, ValueError):
            self.value = None
        self.expires = 0
        self.refreshing = False

    def refresh(self, build, ttl):
        # A reload and a background refresh can arrive together. Serialize the
        # scan and atomic-file replacement so they cannot share the same .tmp.
        with self.refresh_lock:
            value = build()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.path, value)
            self.value = value
            self.expires = time.monotonic() + ttl
            return value

    def background_refresh(self, build, ttl):
        try:
            self.refresh(build, ttl)
        finally:
            with self.lock:
                self.refreshing = False

    def get(self, build, ttl):
        with self.lock:
            if self.value is None:
                return self.refresh(build, ttl)
            if time.monotonic() >= self.expires and not self.refreshing:
                self.refreshing = True
                Thread(target=self.background_refresh, args=(build, ttl), daemon=True).start()
            return self.value


@lru_cache(maxsize=256)
def review_snapshot(key):
    return ReviewSnapshot(key)


@app.get("/api/concerts")
def list_concerts(progress: bool = False):
    snapshot = review_snapshot("concerts-order-v2")
    if progress:
        # Once per page reload, read all three progress columns AND the visible
        # setlist together. Updating products alone left new covers and newly
        # unhidden songs stuck in the persisted index (and browser localStorage).
        # Metadata contents are version-cached; this does not load image bytes.
        return snapshot.refresh(build_concert_index, 60)
    return snapshot.get(build_concert_index, 60)


def build_concert_index():
    selected = list(render_platforms())
    def track(c, it):
        directory = c.song_dir(it)
        folder = directory / "vertical"
        name = it["name"]
        live = name in browser_songs and name in selected_sources and (folder / "original-selected.mp4").is_file()
        baked = (folder / "full.mp4").is_file() and read_json(directory / "song.json", {}).get("preview_mode") != "browser"
        return {"name": name, "title": display_title(it), "notes": it.get("notes"),
                **track_dates(c, it),
                "fps": read_json(directory / "song.json", {}).get("fps") or info.get("fps"),
                "portrait_preview_ready": live or baked,
                "platform_covers_ready": platform_covers_ready(directory),
                "dual_products_ready": dual_products_ready(directory),
                "portrait_release_ready": bool(portrait_release(directory))}

    out = []
    for p in sorted(CONCERTS.iterdir()) if CONCERTS.exists() else []:
        if (p / "concert.json").exists():
            c = Concert(p.name)
            info = read_json(c.info)
            browser_songs = set(read_json(c.dir / "browser_previews.json", {}).get("songs", []))
            selected_sources = read_json(c.dir / "vertical_source.json", {}).get("songs", {})
            if p.name == "singles":
                groups = {}
                for it in visible_items(c):
                    if it["kind"] != "song":
                        continue
                    artist = group_artist(it)
                    slug = single_group(it)
                    event = slug == HALFTIME_SLUG
                    group = groups.setdefault(slug, {"slug": slug, "title": HALFTIME_TITLE if event else artist,
                                                     "artist": "" if event else artist,
                                                     "kind": "event" if event else "artist", "tracks": [], "songs": 0})
                    group["tracks"].append(track(c, it))
                    group["songs"] += 1
                for alias, artist in GROUP_ARTIST_ALIASES.items():
                    if artist_slug(artist) in groups:
                        groups[artist_slug(artist)].setdefault("aliases", []).append(artist_slug(alias))
                out.extend(sorted(groups.values(), key=lambda group: (group["kind"] != "event", group["title"].casefold())))
                continue
            out.append({"slug": p.name, "title": concert_display_title(info, p.name, year_first=True), "artist": info.get("artist"),
                        "date": info.get("date"), "fps": info.get("fps"), "songs": len(c.song_items()),
                        **({"kind": "single"} if info.get("input_kind") == "single" else {}),
                        "tracks": [track(c, it) for it in visible_items(c) if it["kind"] == "song"]})
    concerts = sorted((row for row in out if not row.get("kind")),
                      key=lambda row: row.get("date") or "", reverse=True)
    rows = concerts + [row for row in out if row.get("kind")]
    for row in rows:
        row['delivery_platforms'] = selected
    return rows


def concert_page_info(c, slug, info, songs):
    if c.slug != "singles":
        info = {**info, "title": concert_display_title(info, slug)}
    if slug == HALFTIME_SLUG:
        info = {**info, "title": HALFTIME_TITLE, "artist": ""}
    elif getattr(c, "single_collection", None) and songs:
        artist = group_artist(songs[0])
        info = {**info, "title": artist, "artist": artist}
    if getattr(c, "review_day", None):
        info = {**info, "title": f"单曲 {c.review_day}", "date": c.review_day}
    return info


@app.get("/api/concerts/{slug}")
def get_concert(slug: str, navigation: bool = False):
    """Keep navigation free of per-song asset scans; see the confirmed loading standard."""
    c = concert(slug)
    seg = c.load("segments") or {}
    segs = {s["name"]: s for s in seg.get("items", [])}
    info = read_json(c.info)
    items = visible_items(c)
    songs = [it for it in items if it["kind"] == "song"]
    info = concert_page_info(c, slug, info, songs)
    if navigation:
        return {
            "slug": slug, "has_cover_pool": c.has_cover_pool, "info": info,
            "items": [{"idx": it["idx"], "name": it["name"], "title": display_title(it),
                       "kind": it["kind"]} for it in items],
            "songs": [{"idx": it["idx"], "name": it["name"], "title": display_title(it),
                       "artist": it.get("artist"), "notes": it.get("notes"),
                       "start": segs.get(it["name"], {}).get("start"),
                       "end": segs.get(it["name"], {}).get("end")} for it in songs],
            "gaps": seg.get("gaps", []),
        }
    rv = review.load(c)
    return {
        "slug": slug, "has_cover_pool": c.has_cover_pool, "info": {k: info.get(k) for k in ("title", "artist", "date", "venue", "city", "tour", "duration",
                                                         "fps", "width", "height", "audio_rate", "setlist_url")},
        # Archived media may live on a slow external mount. Listing the concert
        # only needs the link; opening media validates its target separately.
        "source": f"/media/{slug}/source.mp4" if c.source.is_symlink() or c.source.exists() else None,
        "items": [{"idx": it["idx"], "name": it["name"], "title": display_title(it), "kind": it["kind"]} for it in items],
        "songs": [song_summary(c, it, segs, rv) for it in songs],
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
    candidates = [] if c.has_cover_pool else cover_candidates(d)
    selected_id = rv["songs"].get(name, {}).get("cover") or (saved_cover_id(d, candidates) if candidates else None)
    previews = (d / "vertical").glob("preview-*.mp4")
    latest = max((f for f in previews if re.fullmatch(r"preview-\d+\.mp4", f.name)),
                 key=lambda f: f.stat().st_mtime_ns, default=None)
    full = d / "vertical" / "full.mp4"
    portrait = None
    if full.is_file() or latest:
        complete = full.is_file()
        path = full if complete else latest
        length = info["slice"][1] - info["slice"][0]
        portrait = {"url": media_url(c, name, f"vertical/{path.name}"), "format": video_format(path), "full": complete,
                    "start": 0 if complete else int(path.stem.split("-")[1]) / 1000,
                    "duration": length if complete else min(60, length)}
    from workflow.vertical_workflow import revision
    folder = d / "vertical"
    picks = read_json(folder / "candidates.json", [])
    if c.has_cover_pool:
        picks = [r for r in picks if r["file"] == selected_portrait_cover(d)]
    current = revision(d) if picks and (full.is_file() or info.get("preview_mode") == "browser") else None
    released = portrait_release(d, current_only=info.get("source_review") == "pending")
    release_url = None
    if released:
        release_url = media_url(c, name, "vertical/" + released["file"])
    originals = None
    differences = []
    selection = read_json(c.dir / "vertical_source.json", {}).get("songs", {}).get(name)
    if selection:
        selected_kind = selection.get("kind", "ts")
        source = Path(selection["directory"]) / "source.mp4"
        # The selected source is exposed through a stable, allowlisted link.
        link = folder / "original-selected.mp4"
        originals = [{"key": "selected", "label": {"720p": "720p 原片片段", "ts": "TS 原片片段"}.get(selected_kind, "原片片段"),
                      "url": media_url(c, name, "vertical/original-selected.mp4") if link.is_file() else None,
                      "format": video_format(link), "start": 0}]
    browser_portrait = None
    if name in read_json(c.dir / "browser_previews.json", {}).get("songs", []) and originals:
        source = next((row for row in originals if row["url"]), None)
        if source:
            from workflow.portrait_browser import preview_data
            captions = next((d / "subs" / f for f in ("lyrics_poetic.ass", "lyrics_literal.ass", "lyrics.ass")
                             if (d / "subs" / f).is_file()), None)
            browser_portrait = {**preview_data(c, it, d), **source,
                                "captions": ass_lines(captions) if captions else []}
    from workflow.delivery_bundle import posting_paths, submission_records
    paths = posting_paths(d)
    records = submission_records(c, it, paths=paths, entry=rv["songs"].get(name, {}))
    bili, douyin = records["bilibili"], records["douyin"]
    cover = douyin["selected_cover"]
    concert_info = concert_page_info(c, slug, read_json(c.info, {}), [it])
    content_report = read_json(d / "reports/content_check.json", {})
    boundary_review = read_json(d / "reports/boundary_review.json", {})
    production_hold = read_json(c.dir / "production_hold.json", {})
    held = production_hold.get("active") and (not production_hold.get("songs") or name in production_hold["songs"])
    return {
        **base,
        "concert": {"slug": slug, "has_cover_pool": c.has_cover_pool,
                    "info": {key: concert_info.get(key) for key in ("title", "artist")}},
        "posting_paths": paths,
        "douyin_submission": douyin,
        "douyin_cover": cover,
        "source_review": info.get("source_review"),
        "content_review": {"status": content_report.get("status"),
                           "findings": [f for f in boundary_review.get("findings", []) if f.get("status") != "resolved"],
                           "hold_reason": production_hold.get("reason") if held else None},
        "review_mode": info.get("preview_mode"),
        "browser_portrait": browser_portrait,
        "products": product_data(c, name, d),
        "originals": originals, "source_differences": differences,
        "source_note": info.get("source_note"),
        "source_format": original_format(c, d, info),
        "vertical_preview": None if info.get("preview_mode") == "browser" else portrait,
        "portrait_review": {"selected": selected_portrait_cover(d), "revision": current,
                            "covers": [{**r, "url": media_url(c, name, "vertical/" + r["file"])} for r in picks],
                            "released": {**released, "previous": not base["portrait_release_ready"], "url": release_url, "format": video_format(folder / released["file"])} if release_url else None},
        "exp": exp_data(d, f"/media/{slug}/songs/{name}/subs/lyrics.ass"),
        "artist": it.get("artist"), "genius_urls": info.get("genius_urls", []), "slice": info.get("slice"),
        "preview": f"/media/{slug}/songs/{name}/preview.mp4" if (d / "preview.mp4").exists() else None,
        "preview_span": info.get("preview"),
        "preview_format": video_format(d / "preview.mp4"),
        "portrait_nonts60_format": video_format(folder / "compare-nonts-1080p60.mp4"),
        "portrait_nonts60": media_url(c, name, "vertical/compare-nonts-1080p60.mp4")
                           if (folder / "compare-nonts-1080p60.mp4").is_file() else None,
        "portrait_ts60_format": video_format(folder / "compare-ts-1080p60.mp4"),
        "portrait_60_format": video_format(folder / "compare-720p60.mp4"),
        "portrait_ts60": media_url(c, name, "vertical/compare-ts-1080p60.mp4")
                         if (d / "vertical/compare-ts-1080p60.mp4").is_file() else None,
        "portrait_60": media_url(c, name, "vertical/compare-720p60.mp4")
                       if not info.get("source_review") and (d / "vertical/compare-720p60.mp4").is_file() else None,
        # 成品（workflow/song/render.py）：4K60、烧好字幕和水印、FLAC；出来了审核页预览下方直接播
        "final": (media_url(c, name, f"post/{name} 4K60FPS Sub-WaterMark.mp4").replace(" ", "%20")
                  if (d / "post" / f"{name} 4K60FPS Sub-WaterMark.mp4").exists() else None),
        "final_path": str((d / "post" / f"{name} 4K60FPS Sub-WaterMark.mp4").resolve()),
        # 成品目录里所有成品（正式成品 + 对比用的其他编码版本），审核页每个一个播放器
        "finals": finals(c, name, d),
        "covers": [{**x, "file": media_url(c, name, x["file"]),
                    "file_4x3": media_url(c, name, x["file_4x3"]) if x["file_4x3"] else None}
                   for x in candidates],
        "draft": read_json(d / "post_draft.json", {}),
        # 两种展示共用同一份当前投稿资料。
        "bili_upload": json.dumps(bili, ensure_ascii=False, indent=2),
        "bili_upload_path": str((d / "post" / "bili_upload.json").resolve()),
        # 歌曲中间的半透明 logo 水印计划（workflow/song/watermark.py），审核页只做预览，不改视频
        "watermark": read_json(d / "watermark.json", None),
        # 画面内容区域（去掉宽银幕的上下黑边）：左上角 logo、水印都相对它放
        "box": content_box(d),
        "logo_corner": logo_corner(d),   # 片源左上角有台标的场次放右上角
        "review_entry": rv["songs"].get(name, {}), "selected_cover_id": selected_id,
        "cover_selected": bool(rv["songs"].get(name, {}).get("cover")) or has_picked_cover(d),
    }


@app.get("/api/concerts/{slug}/songs/{name}/posting")
def get_posting(slug: str, name: str):
    from workflow.delivery_bundle import submission_records
    c = concert(slug)
    return submission_records(c, song(c, name))


@app.post("/api/concerts/{slug}/songs/{name}/review")
def post_review(slug: str, name: str, body: dict = Body(...)):
    c = concert(slug)
    it = song(c, name)
    try:
        entry = review.save_entry(c, it, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.keys() & {"title", "intro", "tags", "cover"}:
        from workflow.delivery_bundle import write_bundle
        write_bundle(c, it)
    return {"entry": entry, "review": review.effective(c, it, entry)}


def selected_covers(c):
    """展示已保存的真实选择，刷新或单首改选后仍一致。"""
    rows = []
    for it in c.song_items():
        directory = c.song_dir(it)
        selected = selected_portrait_cover(directory)
        pair = cover_attachment(directory, selected)
        if pair:
            rows.append({"name": it["name"], "title": it["title"],
                         "file": media_url(c, it["name"], "vertical/" + selected),
                         "file_4x3": media_url(c, it["name"], "vertical/" + Path(pair["wide_path"]).name) if pair.get("wide_path") else None})
    return rows


def pool_concert(slug):
    c = concert(slug)
    if not c.has_cover_pool:
        raise HTTPException(404, "此场次按单曲选择封面")
    return c


@app.get("/api/concerts/{slug}/cover_pool")
def get_cover_pool(slug: str):
    """整场封面池（workflow/live/cover_pool.py）：每帧的地址、类别、整场时间、在哪首歌里、标没标记；要分封面的歌。"""
    from workflow.live.cover_pool import frames, targets
    c = pool_concert(slug)
    return {"frames": [{**x, "url": f"/media/{slug}/cover_pool/{x['file']}"} for x in frames(c)],
            "songs": [it["title"] for it in targets(c)], "selected": selected_covers(c),
            "quality_stage": read_json(c.dir / "cover_pool/quality.json", {}).get("stage")}


@app.post("/api/concerts/{slug}/cover_pool/mark")
def post_cover_pool_mark(slug: str, body: dict = Body(...)):
    """封面池里标记 / 取消标记一帧（适合做封面）；标记完由 cover_pool.assign 随机分给要做的歌。"""
    from workflow.live.cover_pool import set_mark
    c = pool_concert(slug)
    try:
        n = set_mark(c, body.get("file") or "", bool(body.get("on")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"marked": n}


@app.post("/api/concerts/{slug}/cover_pool/assign")
def post_cover_pool_assign(slug: str):
    """标记完成：标记的画面随机分给要做的歌，每首按歌名排好 16:9 + 4:3 存成封面（cover_pool.assign）。"""
    from workflow.live.cover_pool import assign
    c = pool_concert(slug)
    try:
        assign(slug, portrait=True)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))
    return {"songs": selected_covers(c)}


@app.get("/api/concerts/{slug}/album_covers")
def get_album_covers(slug: str, fresh: bool = False):
    c = concert(slug)
    key = "album-" + hashlib.sha256(slug.encode()).hexdigest()
    snapshot = review_snapshot(key)
    build = lambda: build_album_covers(c, slug)
    data = dict(snapshot.refresh(build, 10) if fresh else snapshot.get(build, 10))
    data["collection"] = collection_info(c, slug, data["title"])
    return data


def collection_info(c, slug, title):
    from workflow.bili_collection import COVER_LAYOUT_VERSION, candidates, cover_output_path, defaults, performance_description, storage_path
    songs = [it for it in visible_items(c) if it["kind"] == "song"]
    options = candidates(c, songs)
    saved = read_json(storage_path(c, slug), {})
    if c.slug != "singles":
        original = read_json(c.info, {})
        title = concert_display_title(original | {"title": original.get("title_zh") or original.get("title") or title}, slug)
    generated = defaults(title, songs)
    description = performance_description(c, songs, title)
    info = generated | saved
    previous_descriptions = {generated["description"], defaults(info["title"], songs)["description"]}
    if description and (not saved.get("description") or saved["description"] in previous_descriptions):
        info["description"] = description
    selected = next((row for row in options if row["id"] == saved.get("source_id")), options[0] if options else None)
    info["source_id"] = selected["id"] if selected else None
    info["cover_path"] = str(cover_output_path(c, slug, selected, info["title"]).resolve()) if selected else None
    info["sources"] = [{k: v for k, v in row.items() if k != "path"} |
                       {"url": media_url(c, row["name"], "covers/ai/" + row["file"])} for row in options]
    version = hashlib.sha256((COVER_LAYOUT_VERSION + json.dumps(info, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]
    info["cover_url"] = f"/api/concerts/{slug}/collection/cover?v={version}" if options else None
    return info


@app.post("/api/concerts/{slug}/collection")
def save_collection(slug: str, body: dict = Body(...)):
    from workflow.bili_collection import candidates, storage_path, validate
    c = concert(slug)
    songs = [it for it in visible_items(c) if it["kind"] == "song"]
    try:
        saved = read_json(storage_path(c, slug), {})
        info = validate({**saved, **body}, candidates(c, songs))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    path = storage_path(c, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, info)
    title = concert_page_info(c, slug, read_json(c.info), songs).get("title") or slug
    return collection_info(c, slug, title)


@app.get("/api/concerts/{slug}/collection/cover")
def collection_cover(slug: str, v: str = "", thumb: bool = False):
    from workflow.bili_collection import candidates, cover_output_path, render_cover
    c = concert(slug)
    songs = [it for it in visible_items(c) if it["kind"] == "song"]
    title = concert_page_info(c, slug, read_json(c.info), songs).get("title") or slug
    info = collection_info(c, slug, title)
    source = next((row for row in candidates(c, songs) if row["id"] == info["source_id"]), None)
    if not source:
        raise HTTPException(404, "暂无可用的 B站 AI 横屏底图")
    output = cover_output_path(c, slug, source, info["title"])
    if not output.exists():
        render_cover(source["path"], info["title"], output)
    return cover_image_response(output, thumb)


def build_album_covers(c, slug):
    rows = []
    songs = [it for it in visible_items(c) if it["kind"] == "song"]
    for number, it in enumerate(songs):
        directory = c.song_dir(it) / "covers/ai"
        masters = [row for row in read_json(directory / "masters.json", [])
                   if row.get("model") and not re.search("seedream", " ".join(str(row.get(key, "")) for key in ("model", "label", "provider")), re.I)]
        variants = read_json(directory / "variants.json", [])
        urls = {}
        for platform, ratio in (("bili-ai", "16x9"), ("douyin-ai", "3x4")):
            filename = next((v["file"] for m in masters for v in reversed(variants)
                             if v.get("master") == m.get("file") and v.get("platform") == platform
                             and v.get("ratio") == ratio and v.get("file") and (directory / v["file"]).is_file()), None)
            urls[ratio] = media_url(c, it["name"], "covers/ai/" + filename) if filename else None
        rows.append({"number": number, "name": it["name"], "title": compact_cover_title(c, it) if len(it["title"].split(" / ")) >= 3 else display_title(it),
                     "url": urls["16x9"], "portrait_url": urls["3x4"]})
    return {"covers": rows, "title": concert_page_info(c, slug, read_json(c.info), songs).get("title") or slug}


@app.get("/api/concerts/{slug}/songs/{name}/cover_design")
def get_cover_design(slug: str, name: str):
    c = concert(slug)
    it = song(c, name)
    directory = c.song_dir(it) / "covers"
    from workflow.cover_frames import candidate_frames
    raw = [{k: v for k, v in row.items() if k not in {"path", "source"}} |
           {"url": f"/api/concerts/{slug}/songs/{name}/cover_frame/{row['id']}"}
           for row in candidate_frames(c, it)]
    generated = [{"file": path.name, "url": media_url(c, name, f"covers/ai/{path.name}")}
                 for path in sorted((directory / "ai").glob("*"))
                 if path.is_file() and not path.name.startswith(("bili-", "douyin-"))
                 and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    # Variants refer to a shared master and are displayed on each platform tab.
    variants = read_json(directory / "ai/variants.json", [])
    masters = read_json(directory / "ai/masters.json", [])
    if masters:
        generated = [row | {"url": media_url(c, name, "covers/ai/" + row["file"]),
                           "reference_url": media_url(c, name, "covers/ai/" + row["reference"]),
                           "original_reference_url": media_url(c, name, "covers/ai/" + row["original_reference"])
                           if row.get("original_reference") else None}
                     for row in masters]
        active = {row["file"] for row in masters}
        variants = [row for row in variants if row["master"] in active]
    generated = [row for row in generated if row["file"] not in {v["file"] for v in variants}]
    for variant in variants:
        variant["url"] = media_url(c, name, "covers/ai/" + variant["file"])
    failures = []
    for run in {row.get("run") for row in masters if row.get("run")}:
        for path in sorted((directory / "ai/runs" / run).glob("candidate-*.json")):
            record = read_json(path, {})
            if record.get("status") == "failed":
                reason = "服务商内容审核未通过" if "SensitiveContent" in record.get("provider_error_code", "") else "生成失败，未自动重试"
                failures.append({"label": record.get("label"), "reason": reason})
    return {"frames": raw, "generated": generated, "variants": variants, "failed_candidates": failures}


_thumbnail_slots = Semaphore(3)


def cover_image_response(source, thumb, cache="no-cache"):
    if not thumb:
        return FileResponse(source, headers={"Cache-Control": cache})
    from PIL import Image, ImageOps
    source = Path(source)
    stat = source.stat()
    key = hashlib.sha256(f"{source}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()
    folder = Path.home() / "Library/Caches/adele-review/cover-thumbnails-v1"
    target = folder / (key + ".jpg")
    if not target.is_file():
        with _thumbnail_slots:
            if not target.is_file():
                folder.mkdir(parents=True, exist_ok=True)
                with Image.open(source) as image:
                    image.draft("RGB", (384, 512))
                    image.thumbnail((384, 512), Image.Resampling.LANCZOS)
                    with tempfile.NamedTemporaryFile(dir=folder) as temp:
                        ImageOps.exif_transpose(image).convert("RGB").save(temp, "JPEG", quality=80)
                        temp.flush()
                        # Publish a complete file atomically; the temp context removes its own link.
                        try:
                            target.hardlink_to(temp.name)
                        except FileExistsError:
                            pass
    return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": cache})


_frame_extraction = Semaphore(2)


@app.get("/api/concerts/{slug}/songs/{name}/cover_frame/{frame_id}")
def get_cover_frame(slug: str, name: str, frame_id: str, thumb: bool = False):
    from workflow.cover_frames import candidate_frames
    from workflow.vertical_cover import original_frame
    import tempfile
    c = concert(slug)
    item = song(c, name)
    row = next((r for r in candidate_frames(c, item) if r["id"] == frame_id), None)
    if row is None:
        raise HTTPException(404, "候选帧不存在")
    if row["path"]:
        return cover_image_response(row["path"], thumb)
    if not row["source"]:
        cached = sorted((c.song_dir(item) / "covers/raw").glob(frame_id + "-*.jpg"))
        if cached:
            return cover_image_response(cached[-1], thumb)
        raise HTTPException(409, "原片离线，接入硬盘后可恢复此帧")
    source = Path(row["source"])
    version = source.stat().st_mtime_ns
    folder = c.song_dir(item) / "covers/raw"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{frame_id}-{version}.jpg"
    with _frame_extraction:
        if not target.is_file():
            try:
                with tempfile.TemporaryDirectory(dir=folder) as temp:
                    pending = Path(temp) / "frame.jpg"
                    original_frame(c, item, row["t"]).save(pending, quality=95)
                    pending.replace(target)
            except (OSError, subprocess.SubprocessError) as error:
                raise HTTPException(503, "原帧提取失败，请重试") from error
    return cover_image_response(target, thumb)


@app.post("/api/concerts/{slug}/songs/{name}/cover_download")
def post_cover_download(slug: str, name: str, body: dict = Body(...)):
    """候选封面「下载」：16:9 和 4:3 两张存成 PNG，放到这首歌成品视频所在的 post/ 目录：
    post/<歌>_cover_picked_<日时分>.png、post/<歌>_cover_picked_4x3_<日时分>.png。
    单曲的 covers 是软链接到 posts/<歌>/covers，成品在 posts/<歌>/post/，顺着软链接找。"""
    from workflow.live.package import save_picked
    c = concert(slug)
    it = song(c, name)
    cid = body.get("id") or ""
    if not re.fullmatch(r"(closeup|half|full|scene|pool|cover)_\d\d", cid):
        raise HTTPException(400, "封面 id 不对")
    saved = save_picked(c, it, cid)
    if not saved:
        raise HTTPException(404, "没有这张封面")
    review.save_entry(c, it, {"cover": cid})
    from workflow.delivery_bundle import write_bundle
    write_bundle(c, it)
    return {"saved": saved}


MEDIA_OK = {".mp4", ".ass", ".jpg", ".jpeg", ".png", ".webp"}


FINAL_LABELS = {"hw_videotoolbox": "硬件编码 H.264 VideoToolbox（对比版）", "hevc_videotoolbox": "硬件编码 HEVC VideoToolbox（对比版）"}


def original_format(c, d, info):
    concert_info = read_json(c.info)
    candidates = [info.get("original_source_file"), info.get("source_file")]
    if c.slug == "singles":
        candidates.extend([d / "source.mp4", (d / "post").resolve().parent / "source.mp4"])
    else:
        candidates.extend([concert_info.get("original_source_file"), concert_info.get("source_file"), c.source])
    for value in filter(None, candidates):
        path = Path(value)
        try:
            stat = path.stat()
            primary = {**probe_original(path, stat.st_mtime_ns, stat.st_size),
                       "filename": path.resolve().name, "size_gb": round(stat.st_size / 1e9, 2)}
            variants = [primary.copy()]
            seen = {path.resolve()}
            for extra in concert_info.get("source_variants", []):
                alternate = Path(extra)
                if alternate.resolve() in seen:
                    continue
                seen.add(alternate.resolve())
                try:
                    metadata = alternate.stat()
                    variants.append({**probe_original(alternate, metadata.st_mtime_ns, metadata.st_size),
                                     "filename": alternate.name, "size_gb": round(metadata.st_size / 1e9, 2)})
                except (OSError, ValueError, KeyError, ZeroDivisionError, subprocess.SubprocessError):
                    continue
            return {**primary, "files": variants}
        except (OSError, ValueError, KeyError, ZeroDivisionError, subprocess.SubprocessError):
            continue
    return {"resolution": "未知分辨率", "fps": "未知帧率", "audio": "未知音频格式"}


@lru_cache(maxsize=256)
def probe_original(path, mtime_ns, size):
    result = subprocess.check_output([shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe",
        "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,field_order:stream_disposition=default",
        "-of", "json", str(path)], timeout=6)
    streams = json.loads(result).get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    video = next((s for s in videos if s.get("disposition", {}).get("default")), next(iter(videos), {}))
    scan = "i" if video.get("field_order") in ("tt", "bb", "tb", "bt") else "p"
    fps = next((video[k] for k in ("avg_frame_rate", "r_frame_rate") if video.get(k) not in (None, "0/0", "0")), None)
    return {
        "resolution": f"{min(video['width'], video['height'])}{scan}" if video.get("height") else "未知分辨率",
        "fps": f"{float(Fraction(fps)):.2f}".rstrip("0").rstrip(".") + " fps" if fps else "未知帧率",
        "audio": " / ".join(dict.fromkeys(s["codec_name"].upper() for s in audios if s.get("codec_name"))) or "无音轨",
    }


def video_format(path):
    try:
        stat = path.stat()
        return _probe_format(path, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, IndexError, KeyError, ZeroDivisionError, subprocess.SubprocessError):
        return None


@lru_cache(maxsize=2048)
def _probe_format(path, mtime_ns, size):
    probe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    result = subprocess.check_output([probe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,field_order",
        "-of", "json", str(path)], timeout=6)
    stream = json.loads(result)["streams"][0]
    for key in ("avg_frame_rate", "r_frame_rate"):
        rate = stream.get(key)
        if rate and rate != "0/0" and Fraction(rate) > 0:
            fps = f"{float(Fraction(rate)):.2f}".rstrip("0").rstrip(".")
            scan = "i" if stream.get("field_order") in ("tt", "bb", "tb", "bt") else "p"
            return f"{min(stream['width'], stream['height'])}{scan}{fps}fps"
    return None


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
                    "path": str(f.resolve()), "format": video_format(f), "gb": round(f.stat().st_size / 1e9, 2)})
    return out


def product_data(c, name, directory):
    manifest = read_json(directory / "products/products.json", {})
    items = []
    for item in manifest.get("items", []):
        file = item.get("file", "")
        if file not in ("bilibili-4k60.mp4", "douyin-1080p60.mp4"):
            continue
        path = directory / "products" / file
        if item.get("status") != "ready" or not path.is_file():
            continue
        items.append({**item, "url": media_url(c, name, "products/" + file),
                      "bytes": path.stat().st_size, "path": str(path.resolve())})
    return {**manifest, "items": items}


def media_url(c, name, rel):
    """封面会原地重新生成（文件名不变）：地址带上修改时间，换了图浏览器一定重新拉，不会用缓存里的旧图。"""
    f = c.song_dir({"name": name}) / rel
    v = f.stat().st_mtime_ns if f.exists() else 0
    return f"/media/{c.slug}/songs/{name}/{rel}?v={v}"


_vertical_render_slot = Semaphore(1)


@app.post("/api/concerts/{slug}/songs/{name}/vertical_preview")
def generate_vertical_preview(slug: str, name: str):
    from workflow.vertical_preview import render
    c = concert(slug)
    item = song(c, name)
    if not _vertical_render_slot.acquire(blocking=False):
        raise HTTPException(409, "正在生成另一支竖屏预览，请稍后重试")
    try:
        settings = read_json(c.dir / "vertical_preview.json", {})
        full = settings.get("full", False) or (c.song_dir(item) / "vertical/full.mp4").is_file()
        render(c, item, force=True, full=full)
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        raise HTTPException(422, f"生成竖屏预览失败：{error}") from error
    finally:
        _vertical_render_slot.release()
    return {"ok": True}


@app.post("/api/concerts/{slug}/songs/{name}/vertical_cover")
def select_vertical_cover(slug: str, name: str, body: dict = Body(...)):
    c = concert(slug)
    item = song(c, name)
    cover = body.get("cover")
    if c.has_cover_pool:
        raise HTTPException(422, "整场演唱会请到封面池选帧并标记完成")
    try:
        attachment = replace_cover_selection(c, item, cover, datetime.now(SHANGHAI))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise HTTPException(422, f"配套封面生成失败：{error}") from error
    from workflow.delivery_bundle import write_bundle
    write_bundle(c, item)
    return {"cover": cover, "douyin_cover": attachment}


@app.post("/api/concerts/{slug}/songs/{name}/reveal_final")
def reveal_final(slug: str, name: str, file: str = ""):
    d = concert(slug)
    directory = d.song_dir(song(d, name))
    file = file or f"{name} 4K60FPS Sub-WaterMark.mp4"
    if file in ("vertical/compare-ts-1080p60.mp4", "vertical/compare-nonts-1080p60.mp4", "vertical/compare-720p60.mp4") or re.fullmatch(
        r"vertical/release-[0-9a-f]{16}\.mp4", file
    ):
        path = directory / file
    elif file in ("products/bilibili-4k60.mp4", "products/douyin-1080p60.mp4"):
        path = directory / file
    elif Path(file).name == file and file.endswith(".mp4") and ".partial." not in file:
        path = directory / "post" / file
    else:
        raise HTTPException(404)
    if not path.is_file():
        raise HTTPException(404, "成片文件不存在或硬盘尚未挂载")
    if subprocess.run(["open", "-R", str(path.resolve())]).returncode:
        raise HTTPException(500, "Finder 未能打开成片目录")
    return {"ok": True}


@app.get("/media/{slug}/{path:path}")
def media(slug: str, path: str, v: str = "", thumb: bool = False):
    c = concert(slug)
    f = (c.dir / path)
    parts = Path(path).parts
    allowed = f.suffix.lower() in MEDIA_OK and (
        path == "source.mp4"
        or (len(parts) == 3 and parts[0] == "songs" and parts[2] in ("preview.mp4", "preview-720p60.mp4"))
        or (len(parts) == 4 and parts[0] == "songs" and parts[2] == "vertical"
            and (parts[3] in ("full.mp4", "original-selected.mp4", "original-ts.mp4", "original-720.mp4", "compare-720p60.mp4", "compare-ts-1080p60.mp4", "compare-nonts-1080p60.mp4") or re.fullmatch(re.escape(parts[1]) + r"-[0-9a-f]{12}-4x3-\d{10}\.jpg", parts[3])
                 or re.fullmatch(r"(?:preview-\d+|release-[0-9a-f]{16})\.mp4|cover-\d+-[0-9a-f]{12}\.jpg", parts[3])))
        or (len(parts) == 4 and parts[0] == "songs" and parts[2] == "subs" and parts[3] in ("lyrics.ass", "lyrics_literal.ass", "lyrics_poetic.ass"))
        or (len(parts) == 4 and parts[0] == "songs" and parts[2] == "products" and parts[3] in ("bilibili-4k60.mp4", "douyin-1080p60.mp4"))
        or (len(parts) >= 4 and parts[0] == "songs" and parts[2] in ("covers", "post"))
        or (len(parts) == 2 and parts[0] == "cover_pool"))   # 整场封面池的原始帧
    if not allowed or ".." in parts or not f.resolve().is_file():
        raise HTTPException(404)
    cache = "no-cache"
    if len(parts) >= 4 and parts[2] == "covers" and v == str(f.stat().st_mtime_ns):
        cache = "private, max-age=31536000, immutable"
    if thumb and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        return cover_image_response(f, True, cache)
    return FileResponse(f, headers={"Cache-Control": cache})


class NoCacheStatic(StaticFiles):
    """前端没有构建和文件指纹：每次回源校验，改了 JS/CSS 刷新就生效。"""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStatic(directory=ROOT / "web", html=True), name="web")
