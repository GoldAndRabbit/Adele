"""Render heart emoji separately from the title typeface in portrait artwork."""
import re

from PIL import Image, ImageDraw, ImageFont

HEART = re.compile(r"(?:🩷|❤)[\ufe0e\ufe0f]?")


def draw_heart_title(canvas, text, font, position, color, max_width, anchor="mm", stroke=0, outline=None):
    if not HEART.search(text):
        return False
    parts = HEART.split(text)
    def width(face):
        return sum(face.getlength(part) for part in parts) + (len(parts) - 1) * face.size
    if width(font) > max_width:
        font = font.font_variant(size=max(1, int(font.size * max_width / width(font))))
    x, y = position
    if anchor == "mm":
        x -= width(font) / 2
    heart = Image.new("RGBA", (180, 180))
    emoji = ImageFont.truetype("/System/Library/Fonts/Apple Color Emoji.ttc", 160)
    ImageDraw.Draw(heart).text((0, 0), "❤️", font=emoji, embedded_color=True)
    heart = heart.crop(heart.getbbox()).resize((font.size, font.size), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    for i, part in enumerate(parts):
        if i:
            canvas.paste(heart, (round(x), round(y - font.size / 2)), heart)
            x += font.size
        draw.text((x, y), part, font=font, fill=color, anchor="lm", stroke_width=stroke, stroke_fill=outline)
        x += font.getlength(part)
    return True
