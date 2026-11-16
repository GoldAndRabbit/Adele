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

from workflow.artist_nicknames import artist_nicknames

# Credits used in Chinese publishing copy when an older draft repeats the English name.
ZH_CREDITS = {
    "Beyoncé": "碧昂丝", "Destiny's Child": "真命天女", "Miranda Lambert": "米兰达·兰伯特",
    "Justin Timberlake": "贾斯汀·汀布莱克", "Kelly Clarkson": "凯莉·克莱森",
    "Carrie Underwood": "凯莉·安德伍德", "Frank Ocean": "弗兰克·奥申",
    "Brandi Carlile": "布兰迪·卡莱尔", "Luke Combs": "卢克·库姆斯",
    "Stevie Wonder": "史蒂维·旺德", "Kacey Musgraves": "凯茜·马斯格雷夫斯",
    "Billie Eilish": "比莉·艾利什", "Travis Barker": "特拉维斯·巴克",
    "Olivia Rodrigo": "奥利维亚·罗德里戈", "Taylor Swift": "泰勒·斯威夫特",
    "Alicia Keys": "艾丽西亚·凯斯", "Dua Lipa": "杜阿·利帕", "Ed Sheeran": "艾德·希兰",
    "Bruno Mars": "布鲁诺·马尔斯", "Rihanna": "蕾哈娜", "Elton John": "埃尔顿·约翰",
    "Sam Smith": "萨姆·史密斯", "Harry Styles": "哈里·斯泰尔斯", "Maroon 5": "魔力红",
    "Miley Cyrus": "麦莉·赛勒斯", "Joni Mitchell": "乔尼·米切尔", "Billy Joel": "比利·乔尔",
}

def posting_inputs(c, it, draft):
    from workflow.vertical_cover import header_labels
    info = c.load("info") or {}
    directory = c.song_dir(it)
    source = read_json(directory / "post" / (it["name"] + ".json"), {})
    performance = {**(source.get("performance") or {}), **(draft.get("performance") or {})}
    labels = header_labels(c, it)
    artist_zh, concert_name = labels["zh"], labels["event"]
    song = {**(source.get("song") or {}), **(draft.get("song") or {})}
    song.update(title=song.get("title") or it["title"], artist=labels["en"])
    if it.get("artist") == "Beyoncé" and "真命天女" in labels["en"]:
        song["artist"] = "Beyoncé & Destiny's Child"
    artist_zh = " & ".join(ZH_CREDITS.get(n, n) for n in artist_zh.split(" & "))
    translation = read_json(directory / "title_translation.json", {}).get("title_zh")
    if translation:
        song["title_zh"] = translation
    if c.slug == "singles":
        english_event = performance.get("event_en") or ""
        if not english_event and not re.search(r"[一-鿿]", it.get("notes") or ""):
            english_event = it.get("notes") or ""
    else:
        english_event = info.get("title_en") or performance.get("event_en") or info.get("title") or ""
    if "2013" in concert_name and "超级碗" in concert_name:
        english_event = "Super Bowl XLVII Halftime Show"
    from post_bili.upload import description as bili_description
    # Exported JSON is derived output, never an input to its own rebuild.
    bili_intro = bili_description(draft) if draft else bili_description(source)
    if not bili_intro:
        bili_intro = read_json(directory / "post/bili_upload.json", {}).get("简介") or ""
    posting_draft = {**draft, "bili_intro": bili_intro, "song": song, "performance": performance, "event_en": english_event,
                     "event_short": info.get("douyin_event_short") or draft.get("event_short", ""),
                     "venue_short": info.get("title_short", "")}
    return posting_draft, concert_name, artist_zh


def caption(draft, event="", artist_zh=""):
    song = draft.get("song") or {}
    title = (song.get("title") or "").strip()
    zh = artist_credit(artist_zh or song.get("artist_zh") or "")
    en = artist_credit(song.get("artist") or "")
    concert = ((draft.get("performance") or {}).get("event") or event or "").strip()
    if not all((title, zh, en, concert)):
        return ""
    aliases = [n for n in artist_nicknames(en, song.get("nicknames_zh")) if n not in (zh, en)]
    return " ".join([title, zh, en, concert, *aliases[:2]])

def douyin_description(intro, tags):
    paragraph = re.split(r"\n[ \t]*\n", (intro or "").replace("\r\n", "\n").replace("\r", "\n").strip(), maxsplit=1)[0]
    # Keep complete topics and reserve room for text, its line break and a full stop.
    chosen = []
    budget = 1000
    for tag in tags:
        if len(chosen) == 5:
            break
        cost = len(tag.encode("utf-16-le")) // 2 + bool(chosen)
        if cost <= budget - (3 if paragraph else 0):
            chosen.append(tag)
            budget -= cost
    available = budget - bool(chosen)
    encoded = paragraph.encode("utf-16-le")
    if len(encoded) > 2 * available:
        prefix = encoded[:2 * (available - 1)].decode("utf-16-le", errors="ignore").rstrip()
        endings = list(re.finditer(r"[。！？!?]", prefix))
        paragraph = prefix[:endings[-1].end()] if endings else prefix + "…"
    return paragraph, chosen, "\n".join(filter(None, (paragraph, " ".join(chosen))))


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
    aliases = artist_nicknames(english, song.get("nicknames_zh"))
    event = (event or (draft.get("performance") or {}).get("event") or "").strip()
    names = zh.replace(" & ", "&")
    nickname = "&".join(aliases)
    parts = [part.strip() for part in re.split(r"\s*/\s*", title) if part.strip()]
    def join(*values):
        return " ".join(x for x in values if x)
    def fits(value):
        return bool(value) and len(value.encode("utf-16-le")) <= 60
    year = re.match(r"(?:19|20)\d{2}", event)
    year = year[0] if year else str((draft.get("performance") or {}).get("date") or song.get("release_year") or "")[:4]
    year = year if re.fullmatch(r"(?:19|20)\d{2}", year) else ""
    bare = event.removeprefix(year).removeprefix("年")
    events = [event, year + bare]
    for alternative in (draft.get("event_short"), draft.get("venue_short")):
        if alternative:
            events.append(year + alternative.replace(year, "").strip(" 年"))
    compact = bare
    for artist in names.split("&"):
        compact = compact.replace(artist, "") if artist != bare else compact
    for long, brief in (("格莱美颁奖典礼", "格莱美"), ("奥斯汀城市极限", "ACL"),
                        ("Lollapalooza", "Lolla"), ("伦敦帕拉迪姆剧院", "伦敦帕拉迪姆"),
                        ("皇家阿尔伯特音乐厅", "阿尔伯特厅")):
        compact = compact.replace(long, brief)
    compact = re.sub(r"(?:演唱会|音乐节|现场)$", "", compact) or bare
    events.append(year + compact)
    grammy = re.search(r"第?(\d+)届格莱美", compact)
    if grammy:
        events.extend([year + "年" + grammy[1] + "届格莱美", year + "格莱美"])
    for landmark, short in (("底特律", "底特律"), ("巴塞罗那", "巴塞罗那"), ("Spotify", "Spotify"),
                            ("Tiny Desk", "Tiny Desk"), ("BBC Radio", "BBC"), ("THE FIRST TAKE", "一镜到底"),
                            ("阿森纳英超夺冠", "阿森纳夺冠"), ("慕尼黑", "慕尼黑"),
                            ("吉米·坎摩尔", "坎摩尔秀"), ("Songline", "Songline"), ("温布利", "温布利")):
        if landmark in bare:
            events.append(year + short)
    if compact.startswith("伦敦"):
        events.append(year + "伦敦")
    events = list(dict.fromkeys(x for x in events if x))
    # A song name and an artist credit are mandatory in every candidate.
    full_title = join(title, names, event)
    tracks = [title, song.get("title_short"), song.get("title_zh")]
    if len(parts) > 1:
        tracks.append(parts[0] + f"等{len(parts)}首")
        translated_parts = re.split(r"\s*/\s*", song.get("title_zh") or "")
        if translated_parts[0]:
            tracks.append(translated_parts[0] + f"等{len(parts)}首")
    tracks = list(dict.fromkeys(x for x in tracks if x))
    both = join(names, english) if names.casefold() != english.casefold() else names
    credits = list(dict.fromkeys(x for x in (names, english, both) if x))
    shortened = []
    for credit in credits:
        first = credit.split("&")[0].strip()
        if first != credit:
            shortened.append(first + "等")
    first_zh = names.split("&")[0].strip()
    first_en = english.split("&")[0].strip()
    if shortened and first_zh.casefold() != first_en.casefold():
        shortened.append(join(first_zh, first_en) + "等")
    short = None
    # Prefer complete song names and complete cast credits. Only shorten the cast
    # when none of those combinations fits the platform's hard limit.
    for cast in (credits, shortened):
        for track in tracks:
            candidates = []
            for credit in cast:
                base = join(track, credit)
                if not fits(base):
                    continue
                translated = song.get("title_zh")
                extras = ["", *events, year]
                if translated and translated != track:
                    extras.extend(join(translated, venue) for venue in ("", year, *events))
                for venue in dict.fromkeys(extras):
                    normalized_venue = re.sub(r"[\W_年]", "", venue.casefold())
                    normalized_base = re.sub(r"[\W_年]", "", base.casefold())
                    if normalized_venue and normalized_venue in normalized_base:
                        continue
                    credit_aliases = aliases if cast is credits else artist_nicknames(english.split("&")[0].strip())
                    for alias in ("", *credit_aliases):
                        if alias and alias in credit:
                            continue
                        candidate = join(track, alias, credit, venue)
                        if fits(candidate):
                            candidates.append(candidate)
                # A translated song title adds information when both names fit.
                translated = song.get("title_zh")
                if translated and translated != track:
                    candidate = join(track, credit, translated)
                    if fits(candidate):
                        candidates.append(candidate)
            if candidates:
                short = max(candidates, key=lambda value: len(value.encode("utf-16-le")))
                break
        if short:
            break
    if short is None:
        raise ValueError(f"30字符内无法同时保留歌名与歌手名：{title} / {english}")
    override = (draft.get("posting_titles") or {}).get("douyin")
    if override:
        if not fits(override):
            raise ValueError("抖音临时标题超过30字符")
        short = full_title = override
    topics = [event, *performers, draft.get("event_en") or (draft.get("performance") or {}).get("event_en", ""), *aliases,
              "欧美现场", song.get("title_zh") or title]
    tags = {}
    for topic in topics:
        tag = re.sub(r"[^\w]", "", topic)
        if tag:
            tags.setdefault(tag.casefold(), "#" + tag)
    body, hashtags, description = douyin_description(draft.get("bili_intro"), tags.values())
    return {"nicknames_zh": aliases, "title": short, "title_full": full_title, "title_chars": len(short.encode("utf-16-le")) // 2,
            "description_body": body, "hashtags": hashtags, "description": description, "description_chars": len(description.encode("utf-16-le")) // 2,
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
