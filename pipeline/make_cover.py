#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
封面候选：从视频里挑清晰的画面，统一打上 朝阳Adele logo + 4K/60FPS 徽章 + 标题 + 副标题（+ 右上角额外 logo），
输出多张候选封面和一张对比总图。

python pipeline/make_cover.py --name sobaniirune --title "そばにいるね" \
    --subtitle "青山テルマ feat. SoulJa · 中日字幕"
# 已选好时间点:   --at 65.2 --at 130
# 右上角加队徽:   --extra-logo cover/psg.png
产物: post/<name>/cover/cover_XX.jpg（16:9，1920x1080）、cover_XX_4x3.jpg（4:3，1440x1080）、
      candidates.jpg / candidates_4x3.jpg（编号总图）
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
TEXT_Y = 0.66  # 副标题基线位置（占画面高度）；B 站底部约 16% 会盖播放量/时长，不要超过 0.84

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


CROP_BOTTOM = 0.0  # 先裁掉画面底部这一比例（去掉搬运视频烧进去的字幕），再放大补满（会放大画面、人脸下移）
MASK_BOTTOM = 0.0  # 不裁切，把底部这一比例的条带模糊+压暗（盖住烧录字幕，保持原构图，人脸更靠上）


def mask_bottom(img, frac):
    """底部条带重度模糊并压暗，上沿羽化过渡。"""
    if frac <= 0:
        return img
    w, h = img.size
    top = int(h * (1 - frac))
    feather = int(h * 0.06)
    blurred = img.filter(ImageFilter.GaussianBlur(28))
    blurred = Image.blend(blurred, Image.new("RGB", img.size, (0, 0, 0)), 0.55)
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    for y in range(max(0, top - feather), h):
        md.line([(0, y), (w, y)], fill=255 if y >= top else int(255 * (y - (top - feather)) / feather))
    return Image.composite(blurred, img, mask)


def grab(video, t):
    pre = f"crop=iw:ih*{1 - CROP_BOTTOM:.3f}:0:0," if CROP_BOTTOM > 0 else ""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"{pre}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    return mask_bottom(Image.frombytes("RGB", (W, H), raw), MASK_BOTTOM)


def has_burned_sub(video, t):
    """画面底部中间有没有烧录字幕（搬运视频常见的黑底白字条）：同时有较多纯白和纯黑像素。"""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                          "-vf", "scale=640:360", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    g = np.frombuffer(raw, np.uint8).reshape(360, 640)
    band = g[int(360 * 0.88):int(360 * 0.97), int(640 * 0.10):int(640 * 0.90)].astype(int)
    # 字幕底框：连续若干列大部分像素接近纯黑；框里有白字。短句的小框也要能认出来
    long_line = (band > 215).mean() > 0.01 and (band < 25).mean() > 0.15
    dark_cols = (band < 30).mean(axis=0) > 0.35
    best, run = 0, 0
    for d in dark_cols:
        run = run + 1 if d else 0
        best = max(best, run)
    short_line = best > band.shape[1] * 0.04 and (band > 200).mean() > 0.003
    return long_line or short_line


def clean_time(video, t, span=2.0, step=0.25):
    """在 t 前后 span 秒内找离 t 最近、底部没有烧录字幕的时刻（两句歌词之间的空档）。"""
    offsets = sorted(np.arange(-span, span + 1e-6, step), key=abs)
    for d in offsets:
        if t + d >= 0 and not has_burned_sub(video, t + d):
            if abs(d) > 1e-6:
                print(f"  {t:.1f}s 有烧录字幕，改用 {t + d:.2f}s")
            return round(t + d, 2)
    print(f"  {t:.1f}s 前后 {span}s 内都有字幕，保留原时间点（可配合 --mask-bottom）")
    return t


INPAINT_SUBS = False  # 只把烧录字幕的黑底白字框抹掉（OpenCV inpaint），画面其他地方不动


def inpaint_subs(img):
    """抹掉底部居中的烧录字幕：按“纯白、低饱和、横向连成一行”的文字定位，外扩一圈盖住黑底框，
    再用周围画面修补（OpenCV inpaint）。背景本来就暗时黑框和背景连成一片，所以按文字找而不是按黑框找。"""
    import cv2

    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    y0, y1 = int(h * 0.88), int(h * 0.985)
    hsv = cv2.cvtColor(arr[y0:y1], cv2.COLOR_RGB2HSV)
    text = ((hsv[..., 2] > 200) & (hsv[..., 1] < 60)).astype(np.uint8) * 255
    text = cv2.dilate(text, np.ones((9, 45), np.uint8))  # 把一行字连成一块
    n, _, stats, _ = cv2.connectedComponentsWithStats(text)
    boxes = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        cx = x + bw / 2
        if bw > w * 0.08 and h * 0.025 < bh < h * 0.11 and w * 0.2 < cx < w * 0.8:
            boxes.append((x, y + y0, bw, bh))
    if not boxes:
        return img
    mask = np.zeros((h, w), np.uint8)
    pad = int(h * 0.026)
    for x, y, bw, bh in boxes:
        mask[max(0, y - pad):min(h, y + bh + pad), max(0, x - pad):min(w, x + bw + pad)] = 255
    out = cv2.inpaint(arr, mask, 11, cv2.INPAINT_TELEA)
    print(f"  抹掉烧录字幕 {len(boxes)} 处")
    return Image.fromarray(out)


def grab_hd(video, t, work):
    """高清取帧：按原始分辨率截帧（含 crop-bottom）→ Real-ESRGAN x4 → Lanczos 缩到封面尺寸并居中裁切。
    1080p 素材裁掉底部字幕后只剩 ~930 行，直接拉伸会糊。"""
    pre = f"crop=iw:ih*{1 - CROP_BOTTOM:.3f}:0:0" if CROP_BOTTOM > 0 else "null"
    tmp = work / "_grab.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                    "-vf", pre, str(tmp)], check=True)
    img = Image.open(tmp).convert("RGB")
    tmp.unlink()
    if INPAINT_SUBS:
        img = inpaint_subs(img)
    img = upscale(img, work, force=True)
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return mask_bottom(img.crop((x, y, x + W, y + H)), MASK_BOTTOM)


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


# ---------------------------------------------------------------- 外部图片（专辑封面等）

def trim_bars(img, tol=25):
    """去掉左右/上下纯色边条（YouTube 音频视频常见的 pillarbox）。"""
    a = np.asarray(img.convert("RGB")).astype(int)
    edge = np.concatenate([a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    if edge.std(axis=0).max() > 12:  # 两边不是纯色，不当作边条
        return img
    diff = np.abs(a - edge.mean(axis=0)).max(axis=2) > tol
    cols = np.where(diff.mean(axis=0) > 0.05)[0]
    rows = np.where(diff.mean(axis=1) > 0.05)[0]
    return img.crop((cols.min(), rows.min(), cols.max() + 1, rows.max() + 1))


def upscale(img, work, force=False):
    """分辨率不够时用 Real-ESRGAN x4 放大，比直接拉伸清楚。"""
    exe, models = ROOT / "realesrgan-ncnn-vulkan", ROOT / "models"
    if (img.height >= H and not force) or not exe.exists() or not (models / "realesrgan-x4plus.bin").exists():
        if force:
            print("  未找到 realesrgan-ncnn-vulkan / models/realesrgan-x4plus，跳过高清化")
        return img
    src, dst = work / "_sr_in.png", work / "_sr_out.png"
    img.save(src)
    subprocess.run([str(exe), "-i", str(src), "-o", str(dst), "-m", str(models),
                    "-n", "realesrgan-x4plus", "-s", "4"], check=True, capture_output=True)
    out = Image.open(dst).convert("RGB")
    src.unlink(); dst.unlink()
    return out


def backdrop_column(strip):
    """把边缘一条像素压成 1px 宽的“背景色”竖条。"""
    col = np.asarray(strip.convert("RGB").resize((1, strip.height), Image.BOX), dtype=np.float32)[:, 0]
    bright = col.mean(axis=1)
    sat = col.max(axis=1) - col.min(axis=1)
    # 以上部 30% 的亮度为基准，比它暗 20 以上的都算人物/阴影，过渡行不会被当成背景
    ref = np.median(bright[: max(1, len(col) * 3 // 10)])
    is_bg = (bright > max(120, ref - 20)) & (sat < 45)
    if not is_bg.any():
        return Image.fromarray(col[:, None].astype(np.uint8)).filter(ImageFilter.GaussianBlur(6))
    last = col[np.argmax(is_bg)].copy()
    fill_from = None
    for y in range(len(col)):
        if is_bg[y]:
            last = col[y].copy()
            fill_from = None
        else:
            fill_from = y if fill_from is None else fill_from
            k = (y - fill_from) / len(col)
            col[y] = last * (1 - 0.35 * k)  # 往下慢慢变暗，接上封面底部的压暗渐变
    img = Image.fromarray(col[:, None].clip(0, 255).astype(np.uint8))
    return img.resize((1, len(col))).filter(ImageFilter.GaussianBlur(40))


def fill_169(img, mode):
    """把任意比例的图放进 16:9：主体完整居中，两侧用 extend（边缘颜色延伸）或 blur（模糊放大底图）补齐。"""
    if abs(img.width / img.height - W / H) < 0.01:
        return img.resize((W, H), Image.LANCZOS)
    if mode == "crop":
        return img.resize((W, int(img.height * W / img.width)), Image.LANCZOS).crop(
            (0, 0, W, H)) if img.width / img.height < W / H else \
            img.resize((int(img.width * H / img.height), H), Image.LANCZOS).crop((0, 0, W, H))
    fg = img.resize((int(img.width * H / img.height), H), Image.LANCZOS)
    x0 = (W - fg.width) // 2
    if mode == "blur":
        bg = img.resize((W, int(img.height * W / img.width)), Image.LANCZOS)
        bg = bg.crop((0, (bg.height - H) // 2, W, (bg.height - H) // 2 + H)).filter(ImageFilter.GaussianBlur(40))
        bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.25)
    else:
        # 两侧只延伸“背景”颜色：边缘像素是人物（暗/有颜色）的行，沿用上方最近的背景色并逐渐加深，
        # 避免把衣服横向拉成一大片黑带
        left = backdrop_column(fg.crop((0, 0, 8, H))).resize((x0 + 90, H))
        right = backdrop_column(fg.crop((fg.width - 8, 0, fg.width, H))).resize((W - x0 - fg.width + 90, H))
        bg = Image.new("RGB", (W, H))
        bg.paste(left, (0, 0))
        bg.paste(right, (x0 + fg.width - 90, 0))
    out = bg.copy()
    mask = Image.new("L", fg.size, 255)
    feather = 90 if mode == "extend" else 24
    md = ImageDraw.Draw(mask)
    for i in range(feather):
        v = int(255 * i / feather)
        md.line([(i, 0), (i, H)], fill=v)
        md.line([(fg.width - 1 - i, 0), (fg.width - 1 - i, H)], fill=v)
    out.paste(fg, (x0, 0), mask)
    return out


def load_image(path, mode, work):
    img = trim_bars(Image.open(path).convert("RGB"))
    print(f"  {Path(path).name}: 去边后 {img.width}x{img.height}")
    return fill_169(upscale(img, work), mode)


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


def ink_width(text, fnt, tracking=0):
    w = fnt.getbbox(text, anchor="ls")
    return (w[2] - w[0]) + tracking * max(0, len(text) - 1)


def fit_width(text, key, target_w, max_size):
    """二分找最大字号，使文字墨迹宽度不超过 target_w，且字号不超过 max_size。"""
    lo, hi = 20, max_size
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ink_width(text, font(key, mid)) <= target_w:
            lo = mid
        else:
            hi = mid - 1
    return font(key, lo)


def draw_text_tracked(canvas, cx, y, text, fnt, tracking, stroke):
    """按字距逐字绘制（白字 + 深色描边 + 投影），整体以 cx 水平居中、y 为基线。"""
    if tracking <= 0:
        draw_text(canvas, (cx, y), text, fnt, stroke=stroke)
        return
    total = ink_width(text, fnt, tracking)
    x = cx - total / 2 - fnt.getbbox(text, anchor="ls")[0]
    for ch in text:
        draw_text(canvas, (x, y), ch, fnt, stroke=stroke, anchor="ls")
        x += fnt.getlength(ch) + tracking


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


def crop_ratio(img, ratio):
    """从 16:9 底图裁出指定宽高比（4:3 封面用）。裁切窗口放在细节最多的位置（人脸/主体通常最清晰），
    而不是固定居中，避免把偏在一侧的人物裁掉半张脸。"""
    w = int(img.height * ratio)
    g = np.asarray(img.convert("L").resize((img.width // 4, img.height // 4)), dtype=np.float32)
    lap = np.abs(g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    col = np.pad(lap[: lap.shape[0] * 2 // 3].sum(axis=0), (1, 1))  # 只看上 2/3，下方会被标题盖住
    win = w // 4
    sums = np.convolve(col, np.ones(win), mode="valid")
    center = (img.width - w) // 2
    # 偏好居中：细节差不多时不乱跑
    bias = 1 - 0.15 * np.abs(np.arange(len(sums)) * 4 - center) / max(center, 1)
    x = int(np.argmax(sums * bias)) * 4
    x = min(max(x, 0), img.width - w)
    return img.crop((x, 0, x + w, img.height))


def compose(frame, a):
    """按画布实际尺寸排版：logo/徽章按高度定大小，标题按当前宽度自适应，16:9 和 4:3 共用。"""
    canvas = frame.convert("RGBA")
    cw, ch = canvas.size

    # 下半部分压暗，保证白字可读
    grad = Image.new("L", (1, ch))
    for y in range(ch):
        grad.putpixel((0, y), int(170 * max(0, (y / ch - 0.4) / 0.6) ** 1.4))
    dark = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    dark.putalpha(grad.resize((cw, ch)))
    canvas.alpha_composite(dark)

    # 左上: 朝阳Adele logo + 4K 徽章
    logo = Image.open(ROOT / a.logo).convert("RGBA")
    lw = int(ch * 0.284)
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    # 白色 logo 在浅色画面上会消失，垫一层模糊的深色投影
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shade = Image.new("RGBA", logo.size, (0, 0, 0, 255))
    shade.putalpha(logo.getchannel("A").point(lambda v: min(255, v * 2)))
    glow.alpha_composite(shade, (62, 38))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)))
    canvas.alpha_composite(logo, (60, 34))
    bw = int(ch * 0.231)
    badge_path = ROOT / a.badge
    b = badge_from_file(badge_path, bw) if badge_path.exists() else badge(bw)
    paste_with_shadow(canvas, b, (60 + (lw - b.width) // 2, 34 + logo.height + 10))

    # 右上: 额外 logo（队徽等）
    x = cw - 50
    for p in a.extra_logo or []:
        ex = Image.open(p).convert("RGBA")
        eh = int(ch * 0.2)
        ex = ex.resize((int(ex.width * eh / ex.height), eh), Image.LANCZOS)
        x -= ex.width
        canvas.alpha_composite(ex, (x, 40))
        x -= 20

    # 标题 + 副标题，整体底边在安全线以上
    title_key = a.title_font or ("cjk" if CJK_RE.search(a.title) else "sans")
    # 标题撑满到接近左右边缘（默认 94% 画布宽），字号再受高度上限约束
    tf = fit_width(a.title, title_key, int(cw * a.title_width), int(ch * 0.30))
    title_w = ink_width(a.title, tf)
    sub_y = int(ch * a.text_y)
    if a.subtitle:
        # “A · B · C” 里的空格在宋体里很宽，白白占掉宽度、字就放不大；去掉分隔符两边的空格
        a.subtitle = re.sub(r"\s*[·・]\s*", "·", a.subtitle)
        # 副标题和标题左右对齐：先按标题宽度定字号；字号太大就封顶，用字距把宽度拉到和标题一样
        sf = fit_width(a.subtitle, "sub", title_w, int(tf.size * 0.6))
        gaps = max(1, len(a.subtitle) - 1)
        tracking = max(0.0, (title_w - ink_width(a.subtitle, sf)) / gaps)
        title_y = sub_y - int(sf.size * 1.12)
        draw_text(canvas, (cw / 2, title_y), a.title, tf)
        draw_text_tracked(canvas, cw / 2, sub_y, a.subtitle, sf, tracking, 0.08)
    else:
        draw_text(canvas, (cw / 2, sub_y), a.title, tf)
    return canvas.convert("RGB")


def contact_sheet(covers, cols=3):
    th = 360
    tw = int(th * covers[0].width / covers[0].height)
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
    p.add_argument("--image", action="append", help="用外部图片（专辑封面等）代替视频帧，可多次")
    p.add_argument("--fill", action="append", choices=["extend", "blur", "crop"],
                   help="非 16:9 图片的补齐方式，可多次（每种出一张），默认 extend + blur")
    p.add_argument("--out-dir", help="输出目录，默认 post/<name>/cover")
    p.add_argument("--text-y", type=float, default=TEXT_Y,
                   help=f"副标题基线占画面高度的比例，越小越靠上（默认 {TEXT_Y}）")
    p.add_argument("--no-sr", dest="sr", action="store_false",
                   help="不做 Real-ESRGAN 高清化（默认对选中的帧做 x4 超分再缩到封面尺寸）")
    p.add_argument("--inpaint-subs", action="store_true",
                   help="画面有烧录字幕时，只把字幕框用周围画面修补掉，保持选定的帧和构图（推荐）")
    p.add_argument("--avoid-subs", action="store_true",
                   help="画面有烧录字幕时，在每个时间点前后 2s 内找没字幕的那一帧（两句之间的空档），不用遮挡（推荐）")
    p.add_argument("--mask-bottom", type=float, default=0.0,
                   help="不裁切，把底部这一比例（如 0.14）模糊压暗来盖住烧录字幕；保持原构图，标题更容易放高（推荐）")
    p.add_argument("--crop-bottom", type=float, default=0.0,
                   help="取帧时先裁掉底部这一比例（如 0.14），用于画面里烧了字幕的搬运视频")
    p.add_argument("--title-width", type=float, default=0.94,
                   help="标题撑满的画布宽度比例（默认 0.94，接近左右边缘）；副标题与标题等宽对齐")
    p.add_argument("--title-font", choices=["sans", "gill", "serif", "cjk"])
    p.add_argument("--extra-logo", action="append", help="右上角额外 logo（png），可多次")
    p.add_argument("--logo", default="adele-logo.png")
    p.add_argument("--badge", default="4K60-logo.jpg", help="4K60 徽章图，不存在时用代码画的徽章")
    a = p.parse_args()

    video = Path(a.video) if a.video else ROOT / "work" / a.name / "source.mp4"
    a.fill = a.fill or ["extend", "blur"]
    globals()["CROP_BOTTOM"] = a.crop_bottom
    globals()["MASK_BOTTOM"] = a.mask_bottom
    globals()["INPAINT_SUBS"] = a.inpaint_subs
    out = Path(a.out_dir) if a.out_dir else ROOT / "post" / a.name / "cover"
    out.mkdir(parents=True, exist_ok=True)

    if a.image:
        frames = [(f"{Path(pth).stem}_{m}", load_image(pth, m, out)) for pth in a.image for m in a.fill]
    else:
        times = a.at if a.at else [t for t, _ in pick_frames(video, a.n)]
        if a.avoid_subs:
            times = [clean_time(video, t) for t in times]
        if a.sr:
            print(f"Real-ESRGAN 高清化 {len(times)} 帧 ...")
            frames = [(f"{t:.1f}s", grab_hd(video, t, out)) for t in times]
        else:
            frames = [(f"{t:.1f}s", grab(video, t)) for t in times]
    # B 站投稿要两种封面：16:9（1920x1080）和 4:3（1440x1080），4:3 单独排版而不是从 16:9 成品裁
    covers, covers43 = [], []
    for i, (label, img) in enumerate(frames, 1):
        c = compose(img, a)
        c43 = compose(crop_ratio(img, 4 / 3), a)
        c.save(out / f"cover_{i:02d}.jpg", quality=95)
        c43.save(out / f"cover_{i:02d}_4x3.jpg", quality=95)
        img.save(out / f"frame_{i:02d}_{label}.jpg", quality=95)
        covers.append(c)
        covers43.append(c43)
        print(f"cover_{i:02d}.jpg + cover_{i:02d}_4x3.jpg  <- {label}")
    contact_sheet(covers).save(out / "candidates.jpg", quality=92)
    contact_sheet(covers43).save(out / "candidates_4x3.jpg", quality=92)
    print(f"候选总图: {out / 'candidates.jpg'}，{out / 'candidates_4x3.jpg'}")


if __name__ == "__main__":
    main()
