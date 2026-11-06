"""Generate the single-line Douyin caption shared by portrait review and posting."""
from datetime import datetime
from zoneinfo import ZoneInfo

import fcntl
from pathlib import Path
import os
import re

from workflow.artist_credit import artist_credit
from workflow.live.paths import read_json, write_json

SHANGHAI = ZoneInfo("Asia/Shanghai")

# Verified Chinese fan names; individual song drafts can supply additional curated names.
NICKNAMES = {"Taylor Swift": ("霉霉",), "Katy Perry": ("水果姐",)}


def posting_inputs(c, it, draft):
    aliases = read_json(c.dir / "vertical_preview.json", {}).get("cover_artist_zh", {})
    info = c.load("info") or {}
    concert_name = it.get("notes") if c.slug == "singles" else info.get("title_zh") or info.get("title")
    song_data = draft.get("song") or {}
    posting_song = {**song_data, "title": song_data.get("title") or it.get("title"),
                    "artist": song_data.get("artist") or it.get("artist")}
    artist_zh = aliases.get(it["name"]) or song_data.get("artist_zh")
    if not artist_zh and posting_song["artist"] == info.get("artist"):
        artist_zh = info.get("artist_zh")
    if not concert_name and c.slug == "singles":
        intro = draft.get("intro") or {}
        match = re.search(r"专辑[《「]([^》」]+)[》」]", intro.get("song", "")) if isinstance(intro, dict) else None
        if match:
            concert_name = f"《{match[1]}》"
    # Reuse the same corrected Chinese credits and year-prefixed event as covers.
    from workflow.vertical_cover import header_labels
    labels = header_labels(c, it)
    artist_zh = labels["zh"]
    concert_name = labels["event"]
    english_event = info.get("title_en") or ((info.get("title") or "") if not re.search(r"[\u3400-\u9fff]", info.get("title") or "") else "")
    posting_draft = {**draft, "song": posting_song, "event_en": english_event,
                     "event_short": info.get("douyin_event_short") or draft.get("event_short", "")}
    return posting_draft, concert_name, artist_zh


def caption(draft, event="", artist_zh=""):
    song = draft.get("song") or {}
    title = (song.get("title") or "").strip()
    zh = artist_credit(artist_zh or song.get("artist_zh") or "")
    en = artist_credit(song.get("artist") or "")
    concert = ((draft.get("performance") or {}).get("event") or event or "").strip()
    if not all((title, zh, en, concert)):
        return ""
    aliases = list(song.get("nicknames_zh") or [])
    for name in en.split(" & "):
        aliases.extend(NICKNAMES.get(name, ()))
    aliases = list(dict.fromkeys(alias.strip() for alias in aliases if alias.strip() and alias.strip() not in (zh, en)))
    return " ".join([title, zh, en, concert, *aliases[:2]])

def submission(draft, event="", artist_zh=""):
    """Fixed Douyin template; hashtags are unique and titles fit 30 UTF-16 units."""
    song = draft.get("song") or {}
    if not caption(draft, event, artist_zh):
        return {}
    title = song["title"].strip()
    zh = artist_credit(artist_zh or song.get("artist_zh") or "").replace("‑", "-")
    zh = re.sub(r"\bJAY-Z\b", "Jay-Z", zh)
    english = artist_credit(song["artist"])
    performers = re.split(r"\s+&\s+|\s+(?:feat\.?|ft\.?|featuring)\s+", english, flags=re.I)
    raw_aliases = song.get("nicknames_zh") or []
    aliases = [raw_aliases] if isinstance(raw_aliases, str) else list(raw_aliases)
    for performer in performers:
        aliases.extend(NICKNAMES.get(performer, ()))
    aliases = list(dict.fromkeys(x.strip() for x in aliases if x.strip()))
    event = (event or (draft.get("performance") or {}).get("event") or "").strip()
    names = zh.replace(" & ", "&")
    nickname = "&".join(aliases)
    parts = [part.strip() for part in re.split(r"\s*/\s*", title) if part.strip()]
    def join(*values):
        return " ".join(x for x in values if x)
    def fits(value):
        return bool(value) and len(value.encode("utf-16-le")) <= 60
    # Shorten the sentence by removing complete fields, never slicing names or words.
    compact_event = (draft.get("event_short") or event).strip()
    event_without_year = re.sub(r"^(?:19|20)\d{2}年?", "", compact_event).strip()
    first_name = names.split("&")[0]
    if len(parts) > 2:
        full_title = f"{names} {event} 歌曲串烧"
        choices = [full_title, join(names, compact_event, "歌曲串烧"),
                   join(names, event_without_year, "歌曲串烧"), join(names, "歌曲串烧"),
                   join(first_name + ("等" if "&" in names else ""), compact_event, "歌曲串烧"),
                   join(first_name, "歌曲串烧"), "演唱会歌曲串烧"]
    else:
        full_title = join(nickname, title, names, event)
        choices = [full_title, join(title, names, compact_event),
                   join(title, names, event_without_year), join(title, names),
                   join(title, nickname), title]
        label = "双曲连唱" if len(parts) == 2 else "现场演唱"
        choices += [join(names, compact_event, label), join(names, label),
                    join(first_name, label), label]
    short = next(value for value in choices if fits(value))
    topics = [event, *performers, draft.get("event_en") or (draft.get("performance") or {}).get("event_en", ""), *aliases, "欧美现场"]
    tags = {}
    for topic in topics:
        tag = re.sub(r"[^\w]", "", topic)
        if tag:
            tags.setdefault(tag.casefold(), "#" + tag)
    description = " ".join(tags.values())
    return {"title": short, "title_full": full_title, "title_chars": len(short.encode("utf-16-le")) // 2,
            "description": description, "description_chars": len(description.encode("utf-16-le")) // 2,
            "declaration": "无需添加自主声明",
            "publish_settings": "仅抖音 · 公开 · 不允许保存 · 立即发布"}


def cover_attachment(directory, cover, *, selected_at=None, prepare=False):
    """Use the Shanghai wall-clock minute when the user selected the cover."""
    match = re.fullmatch(r"cover-\d+-([0-9a-f]{12})\.jpg", cover or "")
    if not match:
        return None
    folder = directory / "vertical"
    if selected_at is None:
        record_path = folder / "selected.json"
        record = read_json(record_path, {})
        if record.get("cover") != cover:
            return None
        # Legacy records were atomically written by the selection handler.
        selected_at = (datetime.fromisoformat(record["selected_at"]) if record.get("selected_at")
                       else datetime.fromtimestamp(record_path.stat().st_mtime, SHANGHAI))
    stamp = selected_at.astimezone(SHANGHAI).strftime("%y%m%d%H%M")
    name = f"{directory.name}-{match[1]}-{stamp}.jpg"
    path = folder / name
    if prepare:
        try:
            os.link(folder / cover, path)
        except FileExistsError:
            pass
    if not path.is_file():
        return None
    wide = folder / f"{directory.name}-{match[1]}-4x3-{stamp}.jpg"
    attachment = {"name": name, "path": str(path.resolve())}
    if wide.is_file():
        attachment["wide_path"] = str(wide.resolve())
    return attachment


def prepare_cover_pair(concert, item, cover, selected_at=None):
    """Reuse the selection timestamp for both attachments, including older selections."""
    from workflow.vertical_cover import wide_cover

    directory = concert.song_dir(item)
    folder = directory / "vertical"
    row = next((r for r in read_json(folder / "candidates.json", []) if r["file"] == cover), None)
    if row is None:
        raise ValueError("请选择当前候选封面")
    attachment = cover_attachment(directory, cover, selected_at=selected_at, prepare=True)
    if not attachment:
        raise ValueError("找不到已选竖封面")
    if "wide_path" not in attachment:
        portrait = Path(attachment["path"])
        stem, stamp = portrait.stem.rsplit("-", 1)
        output = portrait.with_name(f"{stem}-4x3-{stamp}.jpg")
        pool_frame = concert.dir / "cover_pool" / row["pool_frame"] if row.get("pool_frame") else None
        wide_cover(concert, item, row["time"], output, pool_frame=pool_frame)
        attachment["wide_path"] = str(output)
    return attachment

def replace_cover_selection(concert, item, cover, clicked):
    directory = concert.song_dir(item)
    folder = directory / "vertical"
    with (folder / ".selection.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return save_cover_selection_locked(concert, item, cover, clicked)


def save_cover_selection_locked(concert, item, cover, clicked):
    """Caller holds the song's selection lock until both attachments and the record are saved."""
    directory = concert.song_dir(item)
    folder = directory / "vertical"
    record = folder / "selected.json"
    previous = read_json(record, {}).get("cover")
    keep = cover_attachment(directory, previous) or {}
    try:
        attachment = prepare_cover_pair(concert, item, cover, selected_at=clicked)
        write_json(record, {"cover": cover, "selected_at": clicked.isoformat()})
        keep = attachment
    finally:
        # Remove only generated posting attachments, never the immutable frame candidates.
        pattern = re.compile(re.escape(directory.name) + r"-[0-9a-f]{12}-(?:4x3-)?\d{10}\.jpg")
        retained = {keep.get("name"), Path(keep.get("wide_path", "")).name}
        for path in folder.iterdir():
            if pattern.fullmatch(path.name) and path.name not in retained:
                path.unlink(missing_ok=True)
    return attachment
