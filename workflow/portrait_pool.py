"""Build a song's portrait pair using the concert pool's existing frame assignments."""
import fcntl
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path

from workflow.live.cover_pool import frames
from workflow.live.paths import read_json, write_json
from workflow.vertical_cover import cover_image, header_labels, DEFAULT_COVER_PALETTE, COVER_STYLE_VERSION


def pool_candidates(concert, item, assigned=None):
    directory = concert.song_dir(item)
    folder = directory / "vertical"
    folder.mkdir(exist_ok=True)
    with (folder / ".selection.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pool = frames(concert, include_rejected=True)
        previous = read_json(folder / "candidates.json", [])
        record = folder / "selected.json"
        selection = read_json(record, {})
        selected = selection.get("cover")
        retained = next((row for row in previous if row["file"] == selected), None)
        # Only an explicit assignment or an existing user selection creates artwork.
        retained_frame = (retained or {}).get("pool_frame")
        current = assigned or retained_frame
        if not current:
            if retained:
                return [retained]
            return []
        by_file = {row["file"]: row for row in pool}
        if current not in by_file:
            raise ValueError(f"封面池原帧缺失：{current}")
        if assigned and current not in {r["file"] for r in frames(concert)}:
            raise ValueError("这一帧未通过当前封面筛选，请重新选择")
        ordered = [current]
        reserve = []
        song = read_json(directory / "post_draft.json", {}).get("song", {})
        layout = {**header_labels(concert, item), "title": song.get("title_song") or item["title"], "version": COVER_STYLE_VERSION, "palette": DEFAULT_COVER_PALETTE,
                  "title_zh": read_json(directory / "title_translation.json", {}).get("title_zh") or song.get("title_zh", "")}
        known = {r.get("pool_frame"): r for r in previous}
        rows = list(reserve)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            for key in ordered:
                frame = concert.dir / "cover_pool" / key
                old = known.get(key)
                if old and old.get("layout") == layout and old.get("frame_mtime") == frame.stat().st_mtime_ns and (folder / old["file"]).is_file():
                    rows.append(old)
                    continue
                time = by_file[key]["t"]
                out = Path(tmp) / "cover.jpg"
                cover_image(concert, item, time, pool_frame=frame).save(out, quality=95, subsampling=0)
                digest = hashlib.sha256(out.read_bytes()).hexdigest()[:12]
                name = f"cover-{round(time * 1000)}-{digest}.jpg"
                out.replace(folder / name)
                rows.append(dict(file=name, time=time, pool_frame=key, layout=layout, frame_mtime=frame.stat().st_mtime_ns))
        if rows != previous:
            manifest = folder / "candidates.json"
            replacement = next((r for r in rows if retained_frame and r.get("pool_frame") == retained_frame), None)
            if replacement and replacement["file"] != selected:
                from workflow.vertical_post import save_cover_selection_locked, SHANGHAI
                when = (datetime.fromisoformat(selection["selected_at"]) if selection.get("selected_at")
                        else datetime.fromtimestamp(record.stat().st_mtime, SHANGHAI))
                # Both names remain readable until the selected record points to its refreshed artwork.
                write_json(manifest, [*rows, retained])
                try:
                    save_cover_selection_locked(concert, item, replacement["file"], when)
                except Exception:
                    write_json(manifest, previous)
                    raise
            write_json(manifest, rows)
        return rows


def apply_pool_assignment(concert, item, frame, selected_at):
    from workflow.vertical_post import replace_cover_selection
    manifest = concert.song_dir(item) / "vertical/candidates.json"
    previous = read_json(manifest, [])
    try:
        rows = pool_candidates(concert, item, assigned=frame)
        row = next(r for r in rows if r.get("pool_frame") == frame)
        return replace_cover_selection(concert, item, row["file"], selected_at)
    except Exception:
        write_json(manifest, previous)
        raise
