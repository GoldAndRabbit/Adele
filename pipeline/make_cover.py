#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
封面候选：从视频里挑清晰的画面，统一打上 朝阳Adele logo + 4K/60FPS 徽章 + 标题 + 副标题（+ 右上角额外 logo），
输出多张候选封面和一张对比总图。

python pipeline/make_cover.py --name sobaniirune --title "そばにいるね" \
    --subtitle "青山テルマ feat. SoulJa · 中日字幕"
# 已选好时间点:   --at 65.2 --at 130
# 右上角加队徽:   --extra-logo cover/psg.png
产物: post/covers/<name>/cover_XX.jpg（1920x1080）, post/covers/<name>/candidates.jpg
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1920, 1080
SAFE_BOTTOM = 0.84  # B 站封面底部会盖播放量/时长，文字不要低于这里

FONTS = {
    "sans": ("/System/Library/Fonts/Avenir Next.ttc", 8),                    # Avenir Next Heavy
    "gill": ("/System/Library/Fonts/Supplemental/GillSans.ttc", 1),          # Gill Sans Bold（Bzrp 那种）
    "serif": ("/System/Library/Fonts/Supplemental/Georgia Bold.ttf", 0),     # 衬线（Man of the Year 那种）
    "cjk": ("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", 0),            # 日文/中文标题
    "sub": ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),             # 宋体 Black，副标题
    "badge": ("/System/Library/Fonts/Avenir Next.ttc", 8),
}
CJK_RE = re.compile(r"[぀-ヿ㐀-鿿]")


def font(key, size):
    path, idx = FONTS[key]
    return ImageFont.truetype(path, size, index=idx)


# ---------------------------------------------------------------- 选帧

def duration(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(video)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def grab(video, t):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    return Image.frombytes("RGB", (W, H), raw)


def score(img):
    """清晰度（拉普拉斯方差）为主，太暗/太亮扣分。"""
    g = np.asarray(img.convert("L").resize((480, 270)), dtype=np.float32)
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    sharp = lap.var()
    mean = g.mean()
    penalty = 1.0 if 50 < mean < 210 else 0.4
    return sharp * penalty


def pick_frames(video, n, samples=48):
    d = duration(video)
    times = np.linspace(d * 0.08, d * 0.95, samples)
    scored = []
    for t in times:
        img = grab(video, t)
        scored.append((score(img), t, img))
        print(f"  {t:7.1f}s  score={scored[-1][0]:.0f}", flush=True)
    scored.sort(key=lambda x: -x[0])
    gap = d / (n * 1.5)
    chosen = []
    for s, t, img in scored:
        if all(abs(t - c[0]) > gap for c in chosen):
            chosen.append((t, img))
        if len(chosen) == n:
            break
    return sorted(chosen, key=lambda x: x[0])


# ---------------------------------------------------------------- 绘制

def draw_text(canvas, xy, text, fnt, fill=(255, 255, 255), stroke=0.06, anchor="ms"):
    """白字 + 深色描边 + 柔和投影。"""
    sw = max(2, int(fnt.size * stroke))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((xy[0] + sw, xy[1] + sw * 1.5), text, font=fnt, fill=(0, 0, 0, 200),
                                anchor=anchor, stroke_width=sw, stroke_fill=(0, 0, 0, 200))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(sw * 1.2)))
    ImageDraw.Draw(canvas).text(xy, text, font=fnt, fill=fill, anchor=anchor,
                                stroke_width=sw, stroke_fill=(20, 20, 24))


def fit(text, key, start, max_w):
    size = start
    while size > 30:
        f = font(key, size)
        if f.getbbox(text, anchor="ls")[2] <= max_w:
            return f
        size -= 4
    return font(key, size)


def badge(width):
    """金色 4K / 60FPS 徽章。"""
    h = int(width * 0.66)
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    grad = Image.new("RGBA", (width, h))
    top, bot = np.array([255, 226, 120]), np.array([226, 160, 20])
    for y in range(h):
        c = tuple(int(v) for v in top + (bot - top) * y / h) + (255,)
        ImageDraw.Draw(grad).line([(0, y), (width, y)], fill=c)
    mask = Image.new("L", (width, h), 0)
    r = int(width * 0.12)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, h - 1], r, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width - 1, h - 1], r, outline=(40, 30, 10), width=max(3, width // 45))
    d.text((width / 2, h * 0.62), "4K", font=font("badge", int(h * 0.62)), fill=(15, 15, 15), anchor="ms")
    d.text((width / 2, h * 0.9), "60FPS", font=font("badge", int(h * 0.2)), fill=(15, 15, 15), anchor="ms")
    return img


def badge_from_file(path, width):
    """用现成的 4K60 徽章图：缩放、圆角、细深色描边（原图是直角、无透明通道的 jpg）。"""
    src = Image.open(path).convert("RGBA")
    h = int(src.height * width / src.width)
    img = src.resize((width, h), Image.LANCZOS)
    r = int(width * 0.08)
    mask = Image.new("L", (width, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, h - 1], r, fill=255)
    img.putalpha(mask)
    ImageDraw.Draw(img).rounded_rectangle([0, 0, width - 1, h - 1], r, outline=(30, 22, 8, 255),
                                          width=max(2, width // 90))
    return img


def paste_with_shadow(canvas, img, xy, blur=8, offset=(3, 5), alpha=150):
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, alpha))
    sh.putalpha(img.getchannel("A").point(lambda v: v * alpha // 255))
    shadow.alpha_composite(sh, (xy[0] + offset[0], xy[1] + offset[1]))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(img, xy)


def compose(frame, a):
    canvas = frame.convert("RGBA")

    # 下半部分压暗，保证白字可读
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(170 * max(0, (y / H - 0.4) / 0.6) ** 1.4))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    dark.putalpha(grad.resize((W, H)))
    canvas.alpha_composite(dark)

    # 左上: 朝阳Adele logo + 4K 徽章
    logo = Image.open(ROOT / a.logo).convert("RGBA")
    lw = int(W * 0.16)
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    # 白色 logo 在浅色画面上会消失，垫一层模糊的深色投影
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shade = Image.new("RGBA", logo.size, (0, 0, 0, 255))
    shade.putalpha(logo.getchannel("A").point(lambda v: min(255, v * 2)))
    glow.alpha_composite(shade, (62, 38))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)))
    canvas.alpha_composite(logo, (60, 34))
    bw = int(W * 0.13)
    badge_path = ROOT / a.badge
    b = badge_from_file(badge_path, bw) if badge_path.exists() else badge(bw)
    paste_with_shadow(canvas, b, (60 + (lw - b.width) // 2, 34 + logo.height + 10))

    # 右上: 额外 logo（队徽等）
    x = W - 50
    for p in a.extra_logo or []:
        ex = Image.open(p).convert("RGBA")
        eh = int(H * 0.2)
        ex = ex.resize((int(ex.width * eh / ex.height), eh), Image.LANCZOS)
        x -= ex.width
        canvas.alpha_composite(ex, (x, 40))
        x -= 20

    # 标题 + 副标题，整体底边在安全线以上
    title_key = a.title_font or ("cjk" if CJK_RE.search(a.title) else "sans")
    tf = fit(a.title, title_key, 220, int(W * 0.9))
    sf = fit(a.subtitle, "sub", 96, int(W * 0.86)) if a.subtitle else None
    sub_y = int(H * SAFE_BOTTOM)
    title_y = sub_y - (int(sf.size * 1.15) if sf else 0)
    draw_text(canvas, (W / 2, title_y), a.title, tf)
    if sf:
        draw_text(canvas, (W / 2, sub_y), a.subtitle, sf, stroke=0.08)
    return canvas.convert("RGB")


def contact_sheet(covers, cols=3):
    tw, th = 640, 360
    rows = (len(covers) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 16, rows * th + (rows + 1) * 16), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    for i, c in enumerate(covers):
        x = 16 + (i % cols) * (tw + 16)
        y = 16 + (i // cols) * (th + 16)
        sheet.paste(c.resize((tw, th), Image.LANCZOS), (x, y))
        d.rounded_rectangle([x + 8, y + th - 52, x + 60, y + th - 8], 8, fill=(0, 0, 0))
        d.text((x + 34, y + th - 30), str(i + 1), font=font("badge", 32), fill=(255, 210, 60), anchor="mm")
    return sheet


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--title", required=True, help="大标题，一般是歌名")
    p.add_argument("--subtitle", help="副标题，如 'Lorde · 中英字幕'")
    p.add_argument("--video", help="取帧的视频，默认 work/<name>/source.mp4（原始 4K）")
    p.add_argument("--n", type=int, default=6, help="候选数量")
    p.add_argument("--at", type=float, action="append", help="指定取帧时间（秒），可多次")
    p.add_argument("--title-font", choices=["sans", "gill", "serif", "cjk"])
    p.add_argument("--extra-logo", action="append", help="右上角额外 logo（png），可多次")
    p.add_argument("--logo", default="adele-logo.png")
    p.add_argument("--badge", default="4K60-logo.jpg", help="4K60 徽章图，不存在时用代码画的徽章")
    a = p.parse_args()

    video = Path(a.video) if a.video else ROOT / "work" / a.name / "source.mp4"
    out = ROOT / "post" / "covers" / a.name
    out.mkdir(parents=True, exist_ok=True)

    frames = [(t, grab(video, t)) for t in a.at] if a.at else pick_frames(video, a.n)
    covers = []
    for i, (t, img) in enumerate(frames, 1):
        c = compose(img, a)
        c.save(out / f"cover_{i:02d}.jpg", quality=95)
        img.save(out / f"frame_{i:02d}_{t:.1f}s.jpg", quality=95)
        covers.append(c)
        print(f"cover_{i:02d}.jpg  <- {t:.1f}s")
    contact_sheet(covers).save(out / "candidates.jpg", quality=92)
    print(f"候选总图: {out / 'candidates.jpg'}")


if __name__ == "__main__":
    main()
