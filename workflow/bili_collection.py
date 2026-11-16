"""Bilibili collection metadata and title artwork from existing AI masters."""
import hashlib
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from workflow.live.paths import read_json

TITLE_LIMIT = 50
DESCRIPTION_LIMIT = 500
COVER_LAYOUT_VERSION = "v3-centered-single-line"


def storage_path(c, slug):
    # Artist/day views share the singles directory but own separate collection data.
    key = hashlib.sha256(slug.encode()).hexdigest()[:24]
    return c.dir / "collections" / key / "collection.json"


def candidates(c, songs):
    rows = []
    for item in songs:
        directory = c.song_dir(item) / "covers/ai"
        variants = read_json(directory / "variants.json", [])
        for master in read_json(directory / "masters.json", []):
            file = master.get("file", "")
            if not file or Path(file).name != file or not (directory / file).is_file():
                continue
            if not any(v.get("master") == file and v.get("platform") == "bili-ai"
                       and v.get("ratio") == "16x9" and v.get("file")
                       and Path(v["file"]).name == v["file"] and (directory / v["file"]).is_file()
                       for v in variants):
                continue
            key = hashlib.sha256(f"{item['name']}:{file}".encode()).hexdigest()[:24]
            rows.append({"id": key, "name": item["name"], "title": item["title"],
                         "file": file, "path": directory / file})
    return rows


def defaults(title, songs):
    title = title[:TITLE_LIMIT]
    description = f"{title}现场合集。" if songs else f"{title}合集。"
    if songs:
        description += "\n收录曲目：" + "、".join(item["title"] for item in songs) + "。"
    return {"title": title, "description": description[:DESCRIPTION_LIMIT], "sections_enabled": True}


def performance_description(c, songs, title):
    """Migrate existing performance prose; omit song-specific sequencing."""
    event = read_json(c.info, {})
    if c.slug == "singles":
        return None  # A mixed collection must not inherit one event's setting.
    if event.get("artist") not in {"Various Artists", "Various", "群星"}:
        for item in songs:
            draft = read_json(c.song_dir(item) / "post_draft.json", {})
            intro = draft.get("intro", {})
            text = intro.get("performance") if isinstance(intro, dict) else None
            if not isinstance(text, str) or not text.strip():
                continue
            # Keep the event introduction when its final clause describes the
            # source song's place in the set (as in the Olivia ACL draft).
            text = re.sub(r"[，,](?:本曲|这首歌|本首|该曲)[^。！？]*", "", text)
            sentences = re.findall(r"[^。！？]+[。！？]?", text)
            kept = []
            for sentence in sentences:
                sentence = sentence.strip()
                if re.search(r"本曲|这首歌|本首|该曲|整首歌|全曲|第[一二三四五六七八九十百\d]+首|开场曲", sentence):
                    continue
                if "《" + item["title"] + "》" in sentence:
                    continue
                if len("".join(kept)) + len(sentence) <= DESCRIPTION_LIMIT:
                    kept.append(sentence)
            if kept:
                return "".join(kept)
    # For awards and missing prose, use recorded event facts rather than
    # presenting one performer's stage/wardrobe as the entire event.
    name = event.get("title_zh") or event.get("title") or title
    parts = [f"本合集收录「{name}」的现场表演。"]
    if event.get("date"):
        parts.append(f"演出时间：{event['date']}。")
    place = " · ".join(str(event[k]) for k in ("city", "venue") if event.get(k))
    if place:
        parts.append(f"举办地点：{place}。")
    if event.get("tour"):
        parts.append(f"本场属于「{event['tour']}」巡演。")
    if event.get("broadcast"):
        parts.append(f"转播信息：{event['broadcast']}。")
    description = ""
    for part in parts:
        if len(description) + len(part) <= DESCRIPTION_LIMIT:
            description += part
    return description


def validate(body, options):
    title, description = body.get("title"), body.get("description", "")
    if not isinstance(title, str) or not title.strip() or len(title) > TITLE_LIMIT or "\n" in title or "\r" in title:
        raise ValueError("合集标题必填，最多 50 字符，不能换行")
    if not isinstance(description, str) or len(description) > DESCRIPTION_LIMIT:
        raise ValueError("合集简介最多 500 字符")
    enabled = body.get("sections_enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("分组小节必须为开启或关闭")
    source_id = body.get("source_id")
    if source_id and not any(row["id"] == source_id for row in options):
        source_id = options[0]["id"] if options else None
    return {"title": title.strip(), "description": description, "sections_enabled": enabled,
            "source_id": source_id or (options[0]["id"] if options else None)}


def cover_output_path(c, slug, source, title):
    stat = source["path"].stat()
    revision = hashlib.sha256(f"{source['id']}:{stat.st_mtime_ns}:{stat.st_size}:{title}:{COVER_LAYOUT_VERSION}".encode()).hexdigest()[:24]
    return storage_path(c, slug).parent / f"cover-{revision}.jpg"


def title_font_key(title):
    """Use the Chinese face when the display face lacks a title glyph."""
    from workflow.make_cover import font
    probe = font("cjk", 64)
    missing = bytes(probe.getmask(chr(0x10FFFF)))
    return "cjk_sc" if any(not ch.isspace() and bytes(probe.getmask(ch)) == missing
                           for ch in title) else "cjk"


def title_layout(title):
    """Fit the title's actual ink (including outline) into one centered line."""
    from workflow.make_cover import font
    key = title_font_key(title)
    for size in range(112, 1, -1):
        face = font(key, size)
        box = face.getbbox(title, stroke_width=2)
        if box[2] - box[0] <= 1660:
            break
    # Align visible ink, rather than the font's advance or side bearings.
    xy = (960 - (box[0] + box[2]) / 2, 930 - box[3])
    return face, xy, box


def render_cover(source, title, output):
    """Compose fresh title text on the master, never on a song's titled export."""
    with Image.open(source) as image:
        image = ImageOps.fit(image.convert("RGB"), (1920, 1080))
    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    for y in range(540, 1080):
        draw.line((0, y, 1920, y), fill=(0, 0, 0, round(215 * (y - 540) / 540)))
    face, xy, _ = title_layout(title)
    draw.text(xy, title, font=face, fill="white",
              stroke_width=2, stroke_fill=(0, 0, 0, 180))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".jpg", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        image.save(temporary, quality=95)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
