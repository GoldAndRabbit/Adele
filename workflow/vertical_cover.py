"""Compose solid-color portrait and landscape covers around a performance keyframe."""
import io
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
from pathlib import Path

from workflow.portrait_title import HEART, draw_heart_title
from workflow.portrait_header import ARTIST as COVER_ENGLISH, CHINESE as COVER_CHINESE, STYLE
from workflow.artist_credit import artist_credit
from workflow.live.paths import POSTS

from PIL import Image, ImageDraw, ImageFont, ImageOps

from workflow.live.paths import read_json


# One fixed cover style. Legacy palette arguments cannot re-enable old variants.
DEFAULT_COVER_PALETTE = "berry_white"
COVER_STYLE_VERSION = "dark-horse-shared-gold-footer-v6"
COVER_PALETTES = {
    DEFAULT_COVER_PALETTE: {"background": "#713B66", "title": "#FFFFFF", "text": "#FFFFFF"},
}


def cover_ffmpeg():
    search = os.pathsep.join((os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"))
    executable = shutil.which("ffmpeg", path=search)
    if not executable:
        raise FileNotFoundError("找不到封面取帧所需的 ffmpeg")
    return executable


def original_source(concert, item):
    directory = concert.song_dir(item)
    event = concert.load("info")
    policy = read_json(concert.dir / "vertical_source.json", {})
    selected = policy.get("songs", {}).get(item["name"])
    if selected:
        source = Path(selected.get("source", policy["source"]))
        if not source.is_file():
            raise FileNotFoundError("指定片源未挂载，不自动切换版本")
        return source
    override = read_json(directory / "song.json", {}).get("source_file")
    sources = [Path(override or ""), Path(event.get("source_file") or ""), concert.source, directory / "source.mp4"]
    if concert.slug == "singles":
        sources.append(POSTS / item["name"] / "source.mp4")
    source = next((path for path in sources if path.is_file()), None)
    if source is None:
        raise FileNotFoundError("封面选帧需要原始视频，请接入原片后重试")
    return source


def raw_event_label(concert, item):
    if concert.slug != "singles":
        info = concert.load("info")
        return info.get("title_zh") or ""
    override = read_json(concert.dir / "vertical_preview.json", {}).get("event_labels", {}).get(item["name"])
    if override:
        return override
    directory = concert.song_dir(item)
    post = read_json(directory / "post" / (item["name"] + ".json"), {})
    event = post.get("performance", {})
    name = event.get("event_zh") or event.get("event") or item.get("notes", "")
    if name.casefold() in {"official music video", "官方音乐录影带", "官方音乐录像带", "官方mv", "官方 MV".casefold()}:
        album = post.get("song", {}).get("album")
        if not album:
            import re
            intro = read_json(directory / "post_draft.json", {}).get("intro", {})
            match = re.search(r"专辑[《「]([^》」]+)[》」]", str(intro.get("song", "") if isinstance(intro, dict) else intro))
            album = match[1] if match else ""
        return f"《{album}》" if album else ""
    return name


def event_label(concert, item):
    label = raw_event_label(concert, item)
    if not label or label.startswith(("《", "单曲《")) or re.match(r"^(19|20)\d{2}", label):
        return label
    if concert.slug == "singles":
        post = read_json(concert.song_dir(item) / "post" / (item["name"] + ".json"), {})
        date = (post.get("performance") or {}).get("date")
    else:
        date = concert.load("info").get("date")
    year = re.search(r"(?<!\d)((?:19|20)\d{2})(?:年)?(?!\d)", label)
    if year:
        return year[1] + "年" + (label[:year.start()] + label[year.end():]).strip()
    year = re.match(r"((?:19|20)\d{2})", str(date or ""))
    return year[1] + "年" + label if year else label


def header_labels(concert, item):
    directory = concert.song_dir(item)
    song = read_json(directory / "post_draft.json", {}).get("song", {})
    settings = read_json(concert.dir / "vertical_preview.json", {})
    info = concert.load("info")
    name = item["name"]
    en = settings.get("cover_artist_en", {}).get(name) or song.get("artist") or item.get("artist", "")
    zh = settings.get("cover_artist_zh", {}).get(name) or song.get("artist_zh", "")
    if not re.search(r"[\u3400-\u9fff]", zh):
        if en == info.get("artist"):
            zh = info.get("artist_zh") or ""
        zh = settings.get("artist_translations", {}).get(en, zh)
    event = event_label(concert, item)
    album = event.startswith("《") and event.endswith("》")
    if not en or not re.search(r"[\u3400-\u9fff]", zh):
        raise ValueError(f"{name} 缺少歌手中文名，请补充署名后制作")
    if not album and not re.search(r"[\u3400-\u9fff]", event):
        raise ValueError(f"{name} 缺少中文场次或专辑名称")
    return {"en": artist_credit(en), "zh": artist_credit(zh), "event": event}


def supplement_moments(concert, item, begin, end, chosen, ranked, target):
    """Sample the original once and balance distinct compositions across the performance."""
    source = original_source(concert, item)
    selection = read_json(concert.dir / "vertical_source.json", {}).get("songs", {}).get(item["name"])
    seek = begin
    if selection:
        from workflow.vertical_source import prepare
        source = prepare(concert, item)
        seek -= selection["slice"][0]
    size = (32, 18)
    raw = subprocess.check_output([cover_ffmpeg(), "-v", "error", "-ss", str(seek), "-i", str(source),
                                   "-t", str(end - begin), "-vf", "fps=1,scale=32:18",
                                   "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    samples = np.frombuffer(raw, np.uint8).reshape(-1, size[1], size[0], 3).astype(np.float32)
    moments = list(chosen)
    if not len(samples):
        raise ValueError("原片范围内没有可选帧")

    def sample(t):
        return samples[min(len(samples) - 1, max(0, int(t - begin)))]

    pool = list(dict.fromkeys([*ranked, *(begin + i + .5 for i in range(len(samples)))]))
    pool = [t for t in pool if begin <= t < end and t not in moments]
    while len(moments) < target:
        def score(t):
            frame = sample(t)
            gap = min((abs(t - m) for m in moments), default=end - begin)
            visual = min((np.abs(frame - sample(m)).mean() for m in moments), default=45.)
            exposure = min(1., frame.mean() / 38., frame.std() / 32.)
            return exposure * min(1., gap / max(.1, (end - begin) / target)) * min(1., visual / 32.) * (1.2 if t in ranked else 1.)
        if not pool:
            raise ValueError("有效片源过短，无法生成足够的不同关键帧")
        best = max(pool, key=score)
        pool.remove(best)
        moments.append(best)
    return moments


def original_frame(concert, item, at):
    source = original_source(concert, item)
    selection = read_json(concert.dir / "vertical_source.json", {}).get("songs", {}).get(item["name"])
    if selection:
        from workflow.vertical_source import prepare
        source = prepare(concert, item)
        at -= selection["slice"][0]
    raw = subprocess.check_output([cover_ffmpeg(), "-v", "error", "-ss", str(max(0, at)), "-i", str(source),
                                   "-frames:v", "1", "-vf", "scale=1080:-2", "-f", "image2pipe", "-c:v", "png", "-"], timeout=60)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def cover_image(concert, item, at, pool_frame=None, palette=DEFAULT_COVER_PALETTE, feather_edges=95):
    directory = concert.song_dir(item)
    frame = Image.open(pool_frame).convert("RGB") if pool_frame else original_frame(concert, item, at)
    center = ImageOps.contain(frame, (1080, 1080))
    colors = COVER_PALETTES[DEFAULT_COVER_PALETTE]
    canvas = Image.new("RGB", (1080, 1440), colors["background"])
    y = (canvas.height - center.height) // 2
    canvas.paste(center, ((1080 - center.width) // 2, y))
    if feather_edges:
        # Optional preview: soften only the boundaries, before drawing sharp text.
        mask = Image.new("L", canvas.size)
        for row in range(y, y + center.height):
            distance = min(row - y, y + center.height - 1 - row)
            opacity = max(0.0, 1.0 - distance / feather_edges)
            opacity = opacity * opacity * (3 - 2 * opacity)
            mask.paste(round(255 * opacity), (0, row, canvas.width, row + 1))
        canvas = Image.composite(Image.new("RGB", canvas.size, colors["background"]), canvas, mask)
    draw = ImageDraw.Draw(canvas)
    artist = read_json(directory / "post_draft.json")["song"]
    cn, cn_face = COVER_CHINESE
    serif, serif_face = COVER_ENGLISH
    sans, sans_face = COVER_ENGLISH
    def line(title, font, face, size, baseline, color=None, stroke=1):
        color = color or colors["title"]
        if not title:
            return
        if any(ord(c) >= 0x3000 for c in HEART.sub("", title)):
            font, face = cn, cn_face
        f = ImageFont.truetype(font, size, index=face)
        if draw_heart_title(canvas, title, f, (540, baseline), color, 950, stroke=stroke, outline="#000000"):
            return
        if f.getlength(title) > 950:
            f = f.font_variant(size=max(1, int(size * 950 / f.getlength(title))))
        draw.text((540, baseline), title, font=f, fill=color, anchor="mm",
                  stroke_width=stroke, stroke_fill="#000000")
    translation = read_json(directory / "title_translation.json", {}).get("title_zh") or artist.get("title_zh", "")
    line(artist.get("title_song") or item["title"], serif, serif_face, 142, y - 238, stroke=STYLE["title_outline"])
    labels = header_labels(concert, item)
    if not translation:
        raise ValueError("封面缺少已确认的中文歌名，请先运行标题翻译步骤")
    line(translation, cn, cn_face, 66, y - 126)
    line(labels["en"].upper(), sans, sans_face, 62, y - 48)
    lower = y + center.height
    line(labels["event"], cn, cn_face, 68, lower + 70, STYLE["event_color"])
    line("中英字幕", cn, cn_face, 56, lower + 146, STYLE["event_color"])
    return canvas

def wide_cover(concert, item, moment, output, pool_frame=None, palette=DEFAULT_COVER_PALETTE, feather_edges=True):
    """Compose the selected original keyframe into the paired 4:3 posting cover."""
    if output.is_file():
        return
    directory = concert.song_dir(item)
    if pool_frame:
        frame = Image.open(pool_frame).convert("RGB")
    else:
        begin = read_json(directory / "song.json")["slice"][0]
        frame = original_frame(concert, item, round(begin + moment, 3))
    size = (1440, 1080)
    colors = COVER_PALETTES[DEFAULT_COVER_PALETTE]
    canvas = Image.new("RGB", size, colors["background"])
    center = ImageOps.contain(frame, (1440, 810))
    canvas.paste(center, ((1440 - center.width) // 2, 145 + (810 - center.height) // 2))
    # Taller solid bands feather into the unchanged, proportional keyframe.
    overlay = Image.new("RGB", size, colors["background"])
    mask = Image.new("L", size)
    for y in range(size[1]):
        top = max(0.0, min(1.0, (310 - y) / 105))
        bottom = max(0.0, min(1.0, (y - 830) / 105))
        opacity = max(top, bottom)
        opacity = opacity * opacity * (3 - 2 * opacity)
        mask.paste(round(255 * opacity), (0, y, size[0], y + 1))
    if feather_edges:
        canvas = Image.composite(overlay, canvas, mask)
    draw = ImageDraw.Draw(canvas)
    song = read_json(directory / "post_draft.json")["song"]
    cn, cn_face = COVER_CHINESE
    sans, sans_face = COVER_ENGLISH
    serif, serif_face = COVER_ENGLISH

    def line(text, font, index, height, width, pos, anchor, color):
        if not text:
            return
        if any(ord(letter) >= 0x3000 for letter in HEART.sub("", text)):
            font, index = cn, cn_face
        face = ImageFont.truetype(font, height, index=index)
        outline = STYLE["title_outline"] if height >= 80 else STYLE["header_outline"]
        if draw_heart_title(canvas, text, face, pos, color, width, anchor, stroke=outline, outline=STYLE["header_outline_color"]):
            return
        if face.getlength(text) > width:
            face = face.font_variant(size=max(1, int(height * width / face.getlength(text))))
        draw.text(pos, text, font=face, anchor=anchor, fill=color, stroke_width=outline, stroke_fill=STYLE["header_outline_color"])

    gold = colors["title"]
    labels = header_labels(concert, item)
    title = song.get("title_song") or item["title"]
    en = labels["en"].upper()
    translation = read_json(directory / "title_translation.json", {}).get("title_zh") or song.get("title_zh", "")
    if not translation:
        raise ValueError("封面缺少已确认的中文歌名，请先运行标题翻译步骤")
    # Landscape header: song on the left, bilingual artist on the right.
    line(title, serif, serif_face, 88, 880, (55, 58), "lm", gold)
    line(translation, cn, cn_face, 36, 880, (58, 116), "lm", colors["text"])
    line(en, sans, sans_face, 32, 410, (1385, 52), "rm", colors["text"])
    line(labels["zh"], cn, cn_face, 30, 410, (1385, 103), "rm", colors["text"])
    line(labels["event"], cn, cn_face, 46, 1340, (720, 985), "mm", STYLE["event_color"])
    line("中英字幕", cn, cn_face, 36, 1340, (720, 1041), "mm", STYLE["event_color"])
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".jpg") as temp:
        canvas.save(temp, format="JPEG", quality=96, subsampling=0)
        temp.flush()
        # Publish only the complete JPEG. Concurrent identical selections can share it.
        try:
            Path(output).hardlink_to(temp.name)
        except FileExistsError:
            pass
