"""Canonical portrait video header: shared by the renderer and frame verification."""
import re
import json
from pathlib import Path

from PIL import ImageDraw, ImageFont

from workflow.portrait_title import HEART, draw_heart_title

STYLE = json.loads(Path(__file__).with_name("portrait_style.json").read_text())
PINGFANG = next(Path("/System/Library/AssetsV2").glob("com_apple_MobileAsset_Font*/*.asset/AssetData/PingFang.ttc"), None)
CHINESE = (str(PINGFANG), 3) if PINGFANG else ("/System/Library/Fonts/STHeiti Medium.ttc", 0)
ARTIST = ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 0)
TITLE = ARTIST
LINES = {key: (y, size, color) for key, y, size, color in STYLE["header"]}


def draw_artist_name(draw, name, y, font, color, stroke):
    # STHeiti allocates a full character to the middle dot, with the ink at its left.
    # Use a proportional dot but keep the original font for the name itself.
    parts = re.split(r"(·)", re.sub(r"\s*·\s*", "·", name))
    def layout(size):
        name_font = font.font_variant(size=size)
        dot_font = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", size, index=2)
        runs = [(part, dot_font if part == "·" else name_font) for part in parts]
        return runs, sum(face.getlength(part) for part, face in runs)

    runs, width = layout(font.size)
    if width > 960:
        runs, width = layout(max(1, int(font.size * 960 / width)))
    x = (1080 - width) / 2
    for part, face in runs:
        draw.text((x, y), part, font=face, fill=color, stroke_width=stroke, stroke_fill="#28232B", anchor="lm")
        x += face.getlength(part)


def draw_portrait_header(canvas, song, en, zh, event, stroke=True, *, song_zh=None):
    draw = ImageDraw.Draw(canvas)
    expanded = bool(song or event)
    texts = {"song": song, "en": en.upper(), "zh": zh, "song_zh": song_zh or "", "event": event}
    for field, (y, size, color) in LINES.items():
        text = texts[field]
        outline = (STYLE["title_outline"] if field == "song" else STYLE["header_outline"]) if stroke else 0
        if not text:
            continue
        if not expanded and field == "en":
            y, size = 514, 94
        elif not expanded and field == "zh":
            y = 610
        face = ARTIST if field == "en" else CHINESE
        if field == "song" and not any(ord(c) > 0x2fff for c in HEART.sub("", text)):
            face = TITLE
        font = ImageFont.truetype(face[0], size, index=face[1])
        width = 1000 if field == "song" else 960
        if field == "song" and draw_heart_title(canvas, text, font, (540, y), color, width,
                                                stroke=outline, outline=STYLE["header_outline_color"]):
            continue
        if field == "zh" and "·" in text:
            draw_artist_name(draw, text, y, font, color, int(stroke))
            continue
        if font.getlength(text) > width:
            font = font.font_variant(size=max(1, int(size * width / font.getlength(text))))
        draw.text((540, y), text, font=font, fill=color, stroke_width=outline,
                  stroke_fill=STYLE["header_outline_color"], anchor="mm")
