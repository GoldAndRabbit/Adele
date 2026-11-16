"""Stable library ordering metadata, independent of render/file modification times."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from server.metadata import read_json


def date_key(value):
    if not value:
        return None
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%B %d, %Y", "%b %d, %Y", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            pass
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
        except ValueError:
            pass
    return None


def track_dates(c, item):
    directory = c.song_dir(item)
    song = read_json(directory / "song.json", {})
    draft = read_json(directory / "post_draft.json", {})
    cast = draft.get("song") or {}
    values = [item.get("release_date"), song.get("release_date"), cast.get("release_date")]
    values += [row.get("release_date") for row in (song.get("genius") or []) if isinstance(row, dict)]
    values += [item.get("release_year"), song.get("release_year"), cast.get("release_year")]
    published = next((key for value in values if (key := date_key(value))), None)
    added = item.get("added_at") or item.get("entered_at")
    if not added:
        # Existing lists predate added_at. Use birth time, never modification
        # time (regenerating covers or metadata must not move older entries).
        try:
            stat = directory.lstat()
            born = getattr(stat, "st_birthtime", None)
            added = datetime.fromtimestamp(born, ZoneInfo("Asia/Shanghai")).isoformat() if born else None
        except OSError:
            pass
    if not added and item.get("production_day"):
        try:
            added = datetime.strptime(str(item["production_day"]), "%y%m%d").isoformat()
        except ValueError:
            pass
    return {"published_at": published, "added_at": added}
