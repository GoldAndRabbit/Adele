"""Prepare a song for portrait review and export an explicitly approved cut."""
import hashlib
import tempfile
from pathlib import Path


from workflow.live.package import cover_candidates
from workflow.live.paths import Concert, ROOT, read_json, write_json
from workflow.vertical_cover import cover_image, supplement_moments, COVER_STYLE_VERSION


def subtitle(directory):
    for name in ("lyrics_poetic.ass", "lyrics_literal.ass", "lyrics.ass"):
        path = directory / "subs" / name
        if path.is_file():
            return path
    raise ValueError("缺少精校字幕")


def first_lyric(directory):
    import pysubs2
    events = pysubs2.load(str(subtitle(directory)))
    starts = [e.start for e in events if not e.is_comment and e.style == "Default"
              and e.end > e.start and e.plaintext.strip() and not e.plaintext.lstrip().startswith("《")]
    return min(starts) / 1000 if starts else None


def candidates(concert, item, keep_existing=False, redraw=False):
    if concert.has_cover_pool:
        from workflow.portrait_pool import pool_candidates
        return pool_candidates(concert, item)
    directory = concert.song_dir(item)
    info = read_json(directory / "song.json")
    begin, end = info["slice"]
    folder = directory / "vertical"
    folder.mkdir(exist_ok=True)
    # Prefer moments already ranked in the concert cover-design workflow.
    times = []
    for candidate in cover_candidates(directory):
        t = candidate.get("t")
        if t is not None and begin <= t < end and all(abs(t - other) > 1 for other in times):
            times.append(t)
        if len(times) == 6:
            break
    # Optional manually scouted moments are in concert time, just like ranked frames.
    extra = read_json(concert.dir / "vertical_preview.json", {}).get("cover_moments", {}).get(item["name"], [])
    extra = list(dict.fromkeys(t for t in extra if begin <= t < end))
    times = [t for t in times if all(abs(t - x) > 1 for x in extra)][:max(0, 6-len(extra))] + extra
    existing = read_json(folder / "candidates.json", []) if keep_existing else []
    if existing:
        times = [round(begin + r["time"], 3) for r in existing]
    ranked = [r["t"] for r in cover_candidates(directory) if r.get("t") is not None]
    if len(times) < 18:
        times = supplement_moments(concert, item, begin, end, times, ranked, 18)
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        rows = []
        for index, t in enumerate(times):
            if index < len(existing) and not redraw and existing[index].get("style_version") == COVER_STYLE_VERSION:
                rows.append(existing[index])
                continue
            name = f"cover-{round((t - begin) * 1000)}.jpg"
            path = Path(temp) / name
            cover_image(concert, item, t).save(path, quality=95, subsampling=0)
            # Immutable names ensure a changed candidate invalidates its old selection.
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            name = f"{path.stem}-{digest}.jpg"
            path.replace(folder / name)
            rows.append({"file": name, "time": round(t - begin, 3), "style_version": COVER_STYLE_VERSION})
        manifest = Path(temp) / "candidates.json"
        write_json(manifest, rows)
        manifest.replace(folder / manifest.name)




def revision(directory):
    folder = directory / "vertical"
    full = folder / "full.mp4"
    info = read_json(directory / "song.json", {})
    browser = info.get("preview_mode") == "browser"
    if not browser and not full.exists():
        return None
    files = [subtitle(directory), directory / "post_draft.json", directory / "song.json",
             directory / "watermark.json", folder / "candidates.json", directory / "title_translation.json",
             ROOT / "workflow/portrait_style.json", ROOT / "workflow/portrait_header.py",
             ROOT / "workflow/vertical.py"]
    if browser:
        source = Path(info.get("source_file", ""))
        if not source.is_file():
            return None
        h = hashlib.sha256(str((str(source), source.stat().st_mtime_ns, source.stat().st_size)).encode())
        files.append(ROOT / "workflow/portrait_style.json")
    else:
        h = hashlib.sha256(str((full.stat().st_mtime_ns, full.stat().st_size)).encode())
    for f in files:
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()
