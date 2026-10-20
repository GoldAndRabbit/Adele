#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
封面候选：从视频里挑清晰的画面，统一打上 朝阳Adele logo + 4K/60FPS 徽章 + 标题 + 副标题（+ 右上角额外 logo），
输出多张候选封面和一张对比总图。

python workflow/make_cover.py --name sobaniirune --title "そばにいるね" \
    --subtitle "青山テルマ feat. SoulJa · 中日字幕"
# 已选好时间点:   --at 65.2 --at 130
# 右上角加队徽:   --extra-logo cover/psg.png
产物: posts/<name>/post/cover/cover_XX.jpg（16:9，1920x1080）、cover_XX_4x3.jpg（4:3，1440x1080）、
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
TEXT_Y = 0.82  # 副标题基线最低位置（占画面高度），所有景别统一；文字块矮时在徽章底边 ~ 这条线之间居中。B 站底部约 16% 会盖播放量/时长，不要超过 0.84

FONTS = {
    "sans": ("/System/Library/Fonts/Avenir Next.ttc", 8),                    # Avenir Next Heavy
    "gill": ("/System/Library/Fonts/Supplemental/GillSans.ttc", 1),          # Gill Sans Bold（Bzrp 那种）
    "serif": ("/System/Library/Fonts/Supplemental/Georgia Bold.ttf", 0),     # 衬线（Man of the Year 那种）
    "cjk": ("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", 0),            # 默认标题字体（中日英通用）
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
INPAINT_CORNERS = False  # 转播两角的歌名 / 台标：只修补文字笔画（inpaint_corners）；有推广横幅的帧挑帧时跳过
PROMO_MASK = 0.17  # 已经选上的帧有推广横幅（--regrab 时）：退回整条模糊压暗


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


def has_promo(img):
    """转播左下角的推广横幅（二维码 + 彩色底框）：看二维码那一小块——大半纯白、又夹着黑色码点。这种修补不了，挑帧时跳过。
    （按整片亮色判断会把纯红背景、亮色舞台地面误判成横幅）"""
    import cv2
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    hsv = cv2.cvtColor(arr[int(h * 0.835):int(h * 0.92), int(w * 0.05):int(w * 0.115)], cv2.COLOR_RGB2HSV)
    white = ((hsv[..., 2] > 200) & (hsv[..., 1] < 60)).mean()
    return white > 0.3 and (hsv[..., 2] < 60).mean() > 0.08


def inpaint_corners(img):
    """抹掉转播左下角的歌名 / LIVE FROM MADRID 和右下角的台标：只修补白色文字笔画（外扩几像素），
    不像 mask_bottom 那样整条模糊压暗（纯色背景上压暗的一条很显眼）。"""
    import cv2
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    y0, y1 = int(h * 0.86), int(h * 0.985)
    hsv = cv2.cvtColor(arr[y0:y1], cv2.COLOR_RGB2HSV)
    text = ((hsv[..., 2] > 190) & (hsv[..., 1] < 70)).astype(np.uint8)
    text[:, int(w * 0.30):int(w * 0.78)] = 0   # 只管两角
    mask = np.zeros((h, w), np.uint8)
    k = max(3, int(h * 0.008)) | 1
    mask[y0:y1] = cv2.dilate(text * 255, np.ones((k, k), np.uint8), iterations=2)
    if not mask.any():
        return img
    return Image.fromarray(cv2.inpaint(arr, mask, int(h * 0.012), cv2.INPAINT_TELEA))


def grab_hd(video, t, work):
    """高清取帧：按原始分辨率截帧（含 crop-bottom）→ 不够 1080 行才 Real-ESRGAN x4 → Lanczos 缩到封面尺寸并居中裁切。
    1080p 素材裁掉底部字幕后只剩 ~930 行，直接拉伸会糊。本来就够 1080 行的只做一次轻量锐化：
    x4 放大到 8K 再缩回 1080 每帧 ~26 s，效果只相当于去噪 + 锐化。"""
    pre = f"crop=iw:ih*{1 - CROP_BOTTOM:.3f}:0:0" if CROP_BOTTOM > 0 else "null"
    tmp = work / "_grab.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                    "-vf", pre, str(tmp)], check=True)
    img = Image.open(tmp).convert("RGB")
    tmp.unlink()
    if INPAINT_SUBS:
        img = inpaint_subs(img)
    mask = MASK_BOTTOM
    if INPAINT_CORNERS:
        if has_promo(img):
            mask = max(mask, PROMO_MASK)
        else:
            img = inpaint_corners(img)
    sharpen = img.height >= H
    if not sharpen:
        img = upscale(img, work, force=True)
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((x, y, x + W, y + H))
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=60, threshold=2))
    return mask_bottom(img, mask)


# ---------------------------------------------------------------- 按正脸挑帧

YUNET = ROOT / "models" / "yunet" / "face_detection_yunet_2023mar.onnx"
# 脸部清晰度 = 960 宽画面上脸部的拉普拉斯方差 × 脸高占比（大脸皮肤平滑、方差天然低，乘上脸高才和小脸可比）；
# < 本景别第 75 百分位 × BLUR_REL，或 < BLUR_FLOOR，算糊（Lose Yourself：糊的 3.9~5.5，清楚的 6~17；候选里糊的多，p75 只有 ~8）
BLUR_REL, BLUR_RELAX, BLUR_FLOOR = 0.7, 0.55, 3.0  # 先只用 >= 0.7 × p75 的；不够再放宽到 0.55 × p75（再低 Lose Yourself 178s 那种糊的就回来了）
SHOTS = [  # (类别, 中文名, 脸高/画面高 下限, 上限)；标题高度各景别统一（以前按景别抬高，半身 / 全身会压到左上的 4K 徽章）
    ("closeup", "正脸特写", 0.22, 1.00),
    ("half", "正脸半身", 0.09, 0.22),
    ("full", "正脸全身", 0.035, 0.09),
]


SFACE = ROOT / "models" / "yunet" / "face_recognition_sface_2021dec.onnx"


def frontality(f):
    """按五点关键点判断朝向：2 = 正脸（两眼基本水平、鼻子在两眼中间），1 = 接近正脸（3/4 侧脸），0 = 侧脸/歪头。"""
    rex, rey, lex, ley, nx, ny = f[4:10]
    eye_d = abs(lex - rex)
    if eye_d < 1:
        return 0
    tilt, mid = abs(ley - rey) / eye_d, (nx - min(rex, lex)) / eye_d
    if tilt < 0.15 and 0.3 < mid < 0.7:
        return 2
    return 1 if tilt < 0.3 and -0.8 < mid < 1.8 else 0


def frontal_faces(det, img, level=2):
    """YuNet 检测，留下朝向 >= level 的脸（见 frontality）。返回 (脸列表, 检测到的人脸总数, BGR 图)。"""
    a = np.asarray(img.convert("RGB"))[:, :, ::-1].copy()
    det.setInputSize((a.shape[1], a.shape[0]))
    _, faces = det.detect(a)
    faces = faces if faces is not None else []
    out = []
    for f in faces:
        if f[14] >= 0.8 and frontality(f) >= level:
            out.append(f)
    return out, len(faces), a


def pick_faces(video, per=4, step=1.0, gap=6.0, max_faces=4, t0=None, t1=None):
    want = per if isinstance(per, dict) else {k: per for k, *_ in SHOTS}   # 每个景别各几张
    """1) 每 step 秒取一帧，YuNet 找正脸，SFace 提取人脸特征；
    2) 按特征聚类：出现得多、脸又大的那几个人是演唱者（观众一般只闪过一两次），可以有多个（组合/合唱）；
    3) 只保留演唱者的正脸、且画面里人脸不超过 max_faces 张（排除观众大全景）的帧，
       按脸高/画面高分成 特写 / 半身 / 全身，每类挑 per 张（打分 = 置信度 × 脸部清晰度 × 居中，时间间隔 >= gap）；
    4) 正脸不够时依次用 接近正脸（3/4 侧脸）的演唱者帧、和演唱者相似的结构候选补位（老电视节目常常几乎没有纯正脸）。"""
    import cv2
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (960, 540), 0.8, 0.3, 50)
    rec = cv2.FaceRecognizerSF.create(str(SFACE), "")
    d = duration(video)
    faces_all = []  # (t, ratio, conf, sharp, center, feature, n_faces)
    for t in np.arange(t0 if t0 is not None else 1.0, (t1 if t1 is not None else d) - 1.0, step):
        img = grab(video, float(t))
        if INPAINT_CORNERS and has_promo(img):   # 推广横幅挡在左下角，修补不了
            continue
        img = img.resize((960, 540))
        fr, n, bgr = frontal_faces(det, img, level=1)
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        for f in fr:
            x, y, w, h = [float(v) for v in f[:4]]
            y0, y1, x0, x1 = int(max(0, y)), int(min(540, y + h)), int(max(0, x)), int(min(960, x + w))
            roi = g[y0:y1, x0:x1]
            if roi.size < 100:
                continue
            if float(roi.mean()) < 45:  # 脸部太暗（观众席、背光），不当封面
                continue
            sharp = float(cv2.Laplacian(roi, cv2.CV_32F).var())
            feat = rec.feature(rec.alignCrop(bgr, f)).flatten()
            feat = feat / (np.linalg.norm(feat) + 1e-9)
            faces_all.append((float(t), h / 540, float(f[14]), sharp, 1 - abs((x + w / 2) / 960 - 0.5), feat, n,
                              (y + h / 2) / 540, frontality(f)))
    if not faces_all:
        return {k: [] for k, *_ in SHOTS}

    # 聚类（贪心，余弦 >= 0.4 算同一个人），权重 = 出现次数 × 平均脸大小
    clusters = []
    for i, fa in enumerate(faces_all):
        for c in clusters:
            if float(fa[5] @ c["center"]) >= 0.4:
                c["idx"].append(i)
                c["center"] = c["center"] + (fa[5] - c["center"]) / len(c["idx"])
                c["center"] /= np.linalg.norm(c["center"]) + 1e-9
                break
        else:
            clusters.append({"idx": [i], "center": fa[5].copy()})
    for c in clusters:
        c["w"] = len(c["idx"]) * float(np.mean([faces_all[i][1] for i in c["idx"]]))
    clusters.sort(key=lambda c: -c["w"])
    top = clusters[0]["w"]
    performers = [c for c in clusters if c["w"] >= 0.3 * top and len(c["idx"]) >= 3]
    keep = {i for c in performers for i in c["idx"]}
    print(f"  正脸 {sum(fa[8] == 2 for fa in faces_all)} 个 + 接近正脸 {sum(fa[8] == 1 for fa in faces_all)} 个，聚成 {len(clusters)} 人，判定演唱者 {len(performers)} 人"
          f"（出现 {[len(c['idx']) for c in performers]} 次）")

    # 候选 (档位, 分数, 时间)：档位 3 = 正脸，2 = 接近正脸，1 = 结构补位；先按档位再按分数挑
    cands = {k: [] for k, *_ in SHOTS}
    for i, (t, ratio, conf, sharp, center, _, n, cy, fl) in enumerate(faces_all):
        for k, _, lo, hi in SHOTS:
            if not want[k] or not lo <= ratio < hi:
                continue
            if k == "full":
                # 全身镜头脸太小，人脸识别不可靠：要求脸在画面上半部分（舞台）、画面里人脸不超过 3 张
                if cy > 0.55 or n > 3:
                    continue
            elif i not in keep or n > max_faces:  # 特写/半身：必须是识别出的演唱者
                continue
            cands[k].append((fl + 1, conf * np.log1p(sharp) * center, t, sharp * ratio))
    # 某一类识别确认的帧不够 per 张：放宽补位（脸在上半部分、人脸不超过 3 张、和某位演唱者有一定相似度，挡掉观众）
    # 和演唱者每一张确认过的大正脸逐张比（比聚类中心稳：中心会被侧脸带偏；全身镜头的小脸特征不可靠，不当参照）
    refs = np.array([faces_all[i][5] for i in keep if faces_all[i][8] == 2 and faces_all[i][1] >= 0.09]).reshape(-1, 128)
    for k, _, lo, hi in SHOTS:
        if k == "full" or not want[k] or len({c[2] for c in cands[k]}) >= want[k]:
            continue
        have = {c[2] for c in cands[k]}
        for i, (t, ratio, conf, sharp, center, feat, n, cy, fl) in enumerate(faces_all):
            like = float((refs @ feat).max()) if len(refs) else 0.0
            if lo <= ratio < hi and t not in have and cy <= 0.6 and n <= 3 and like >= 0.35:
                cands[k].append((1, conf * np.log1p(sharp) * center, t, sharp * ratio))
    # 去掉糊的（动态模糊 / 失焦）：见 BLUR_REL。清晰度和片源关系很大（4K 转播特写比 2009 年的 Lose Yourself 高好几倍），
    # 只能按本首、本景别相对比。先只用清楚的挑；不够再放宽到 BLUR_RELAX 补（真糊的仍然进不来）
    def choose(k, n):
        if not n or not cands[k]:
            return [], 0, 0
        p75 = float(np.percentile([c[3] for c in cands[k]], 75))
        strict, relaxed = max(BLUR_FLOOR, BLUR_REL * p75), max(BLUR_FLOOR, BLUR_RELAX * p75)
        chosen = []
        for thr in (strict, relaxed):
            pool = sorted((c for c in cands[k] if c[3] >= thr), reverse=True)
            # 间隔 gap 秒挑；凑不够就把间隔减半再挑（同一个镜头里也能挑出不太一样的两张）；已选的保留
            for g in (gap, gap / 2, gap / 4):
                for _, _, t, _ in pool:
                    if len(chosen) == n:
                        break
                    if all(abs(t - c) >= g for c in chosen):
                        chosen.append(t)
            if len(chosen) == n:
                break
        return chosen, len({c[2] for c in cands[k] if c[3] < thr}), thr

    # 特写 + 半身一共要 sum(want) 张：一类不够，差额让另一类多挑（La fuerte 转播几乎没有特写，就多给半身）
    res = {k: choose(k, want[k]) for k, *_ in SHOTS}
    for k, *_ in SHOTS:
        if not want[k]:
            continue
        spare = sum(max(0, want[o] - len(res[o][0])) for o, *_ in SHOTS if o != k and want[o])
        if spare and len(res[k][0]) == want[k]:
            res[k] = choose(k, want[k] + spare)
    picked = {}
    for k, *_ in SHOTS:
        if not want[k]:
            picked[k] = []
            continue
        chosen, blurry, thr = res[k]
        if blurry:
            print(f"  {k}: 去掉糊的 {blurry} 帧（脸部清晰度 < {thr:.1f}）")
        picked[k] = sorted(chosen)
        tier = {t: max(c[0] for c in cands[k] if c[2] == t) for t in chosen}
        print(f"  {k}: 候选 {len(cands[k])} 帧，选 {len(chosen)} 张 "
              + str([f"{x:.0f}s{'' if tier[x] == 3 else '(近正脸)' if tier[x] == 2 else '(补位)'}" for x in picked[k]]))
    total, need = sum(len(v) for v in picked.values()), sum(want.values())
    if total < need:
        print(f"  ⚠ 一共只找到 {total} 张可靠的演唱者画面（要 {need} 张，宁缺毋滥），需要的话用 --at 手动补")
    return picked


def score(img):
    """清晰度（拉普拉斯方差）为主，太暗/太亮扣分。"""
    g = np.asarray(img.convert("L").resize((480, 270)), dtype=np.float32)
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    sharp = lap.var()
    mean = g.mean()
    penalty = 1.0 if 50 < mean < 210 else 0.4
    return sharp * penalty


def pick_frames(video, n, samples=48, t0=None, t1=None):
    lo, hi = t0 or 0.0, t1 or duration(video)
    d = hi - lo
    times = np.linspace(lo + d * 0.08, lo + d * 0.95, samples)
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
    exe, models = ROOT / "bin" / "realesrgan-ncnn-vulkan", ROOT / "models" / "realesrgan"
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
    badge_bottom = 34 + logo.height + 10 + b.height
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
    title_key = a.title_font or "cjk"  # 中日英标题统一用冬青黑体 W8，和之前的封面一致
    # 标题撑满到接近左右边缘（默认 94% 画布宽），字号再受高度上限约束
    sub_y = int(ch * (a.text_y - a.text_lift))
    if a.subtitle:
        # 宋体的「·」是全角字、两边自带留白，再加空格就空得很丑（也白白占宽度、字放不大）；去掉分隔符两边的空格
        a.subtitle = re.sub(r"\s*[·・]\s*", "·", a.subtitle)

    def layout(max_size):
        tf = fit_width(a.title, title_key, int(cw * a.title_width), max_size)
        title_w = ink_width(a.title, tf)
        if not a.subtitle:
            return tf, None, 0.0, sub_y
        if a.sub_fit == "natural":
            # 居中，宽度 = 标题宽的 85%：先按正常字距放大字号；长标题（BZRP Music Sessions #53）字小，副标题要比标题还大
            # 才够宽，字号就封顶在标题字号，差的宽度用字距补齐。整块变高没关系，后面标题会自动缩小避开徽章、整块再居中
            sub_w = int(title_w * 0.85)
            sf = fit_width(a.subtitle, "sub", sub_w, tf.size)
            tracking = max(0.0, (sub_w - ink_width(a.subtitle, sf)) / max(1, len(a.subtitle) - 1))
        else:
            # 副标题和标题左右对齐：先按标题宽度定字号；字号太大就封顶，用字距把宽度拉到和标题一样
            sf = fit_width(a.subtitle, "sub", title_w, int(tf.size * 0.68))
            tracking = max(0.0, (title_w - ink_width(a.subtitle, sf)) / max(1, len(a.subtitle) - 1))
        return tf, sf, tracking, sub_y - int(sf.size * 1.12)

    # 标题撑满宽度，必然横跨左上角的 logo + 4K 徽章：字顶不能高过徽章底边，太高就缩小字号（底边位置不变）
    top_limit = badge_bottom + int(ch * 0.03)
    max_size = int(ch * 0.30)
    while True:
        tf, sf, tracking, title_y = layout(max_size)
        top = title_y + tf.getbbox(a.title, anchor="ms")[1]
        if top >= top_limit or max_size <= 40:
            break
        max_size = int(max_size * 0.95)
    # 整块文字在「徽章底边 ~ text_y」之间垂直居中：短标题字大、本来就撑满；长标题（BZRP Music Sessions #53）字小、
    # 块矮，底边对齐的话会沉在最下面，往上挪到中间
    shift = max(0, (top - top_limit) // 2)
    draw_text(canvas, (cw / 2, title_y - shift), a.title, tf)
    if sf:
        draw_text_tracked(canvas, cw / 2, sub_y - shift, a.subtitle, sf, tracking, 0.08)
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
    p.add_argument("--video", help="取帧的视频，默认 posts/<name>/source.mp4（原始 4K）")
    p.add_argument("--select", choices=["faces", "sharp"], default="faces",
                   help="faces（默认）：正脸特写/半身/全身各 --per 张；sharp：按清晰度挑 --n 张（旧）")
    p.add_argument("--per", type=int, default=4, help="faces 模式每个景别几张")
    p.add_argument("--closeup-min", type=float, default=0.22,
                   help="特写的脸高下限（占画面高），默认 0.22；演唱会转播大特写少，可降到 0.14（半身的上限跟着变）")
    p.add_argument("--per-shot", help="faces 模式按景别指定张数，如 closeup=6,half=3,full=3（覆盖 --per）")
    p.add_argument("--n", type=int, default=6, help="sharp 模式候选数量")
    p.add_argument("--at", type=float, action="append", help="指定取帧时间（秒），可多次")
    p.add_argument("--image", action="append", help="用外部图片（专辑封面等）代替视频帧，可多次")
    p.add_argument("--start", type=float, help="只在视频的这一段里挑帧（秒），整场演唱会按单曲取封面用")
    p.add_argument("--end", type=float)
    p.add_argument("--fill", action="append", choices=["extend", "blur", "crop"],
                   help="非 16:9 图片的补齐方式，可多次（每种出一张），默认 extend + blur")
    p.add_argument("--out-dir", help="输出目录，默认 posts/<name>/post/cover")
    p.add_argument("--text-lift", type=float, default=0.0,
                   help="文字整体上移（占画面高度），各景别的默认高度都减去它；底部有遮挡 / 压暗条时用")
    p.add_argument("--text-y", type=float, default=TEXT_Y,
                   help=f"副标题基线占画面高度的比例，越小越靠上（默认 {TEXT_Y}）")
    p.add_argument("--no-sr", dest="sr", action="store_false",
                   help="不做 Real-ESRGAN 高清化（默认对选中的帧做 x4 超分再缩到封面尺寸）")
    p.add_argument("--inpaint-corners", action="store_true",
                   help="转播画面两角的歌名 / 台标：只修补文字笔画，不整条压暗；有推广横幅的帧不选")
    p.add_argument("--regrab", action="store_true",
                   help="不重新挑帧：按 out-dir 里已有 frame_*_<秒>s.jpg 的时间点重新高清取帧（底部处理换了时用），再排版")
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
    p.add_argument("--sub-fit", choices=["stretch", "natural"], default="stretch",
                   help="副标题：stretch（默认）拉开字距和标题等宽；natural 正常字距、不刻意拉宽")
    p.add_argument("--recompose", action="store_true",
                   help="只重排文字：用 out-dir 里已有的高清帧（frame_*.jpg）重新生成封面，不重新挑帧、不重新高清化")
    p.add_argument("--extra-logo", action="append", help="右上角额外 logo（png），可多次")
    p.add_argument("--logo", default="assets/adele-logo.png")
    p.add_argument("--badge", default="assets/4K60-logo.jpg", help="4K60 徽章图，不存在时用代码画的徽章")
    a = p.parse_args()

    video = Path(a.video) if a.video else ROOT / "posts" / a.name / "source.mp4"
    a.fill = a.fill or ["extend", "blur"]
    globals()["CROP_BOTTOM"] = a.crop_bottom
    globals()["MASK_BOTTOM"] = a.mask_bottom
    globals()["INPAINT_SUBS"] = a.inpaint_subs
    globals()["INPAINT_CORNERS"] = a.inpaint_corners
    out = Path(a.out_dir) if a.out_dir else ROOT / "posts" / a.name / "post" / "cover"
    out.mkdir(parents=True, exist_ok=True)

    if a.regrab:
        for f in sorted(out.glob("frame_*.jpg")):
            m = re.match(r"frame_(?:(closeup|half|full)_)?(\d\d)_([\d.]+)s\.jpg$", f.name)
            if not m:
                continue
            k, t = m[1] or "cover", float(m[3])
            img = grab_hd(video, t, out) if a.sr else grab(video, t)
            img.save(f, quality=95)
            compose(img, a).save(out / f"{k}_{m[2]}.jpg", quality=95)
            compose(crop_ratio(img, 4 / 3), a).save(out / f"{k}_{m[2]}_4x3.jpg", quality=95)
            print(f"{k}_{m[2]}.jpg + 4x3  <- {t:.1f}s（重新取帧）", flush=True)
        return

    if a.recompose:
        for f in sorted(out.glob("frame_*.jpg")):
            m = re.match(r"frame_(?:(closeup|half|full)_)?(\d\d)_", f.name)
            if not m:
                continue
            k = m[1] or "cover"
            img = Image.open(f).convert("RGB")
            compose(img, a).save(out / f"{k}_{m[2]}.jpg", quality=95)
            compose(crop_ratio(img, 4 / 3), a).save(out / f"{k}_{m[2]}_4x3.jpg", quality=95)
            print(f"{k}_{m[2]}.jpg + 4x3  <- {f.name}")
        return

    if not a.image and not a.at and a.select == "faces":
        # 默认：正脸特写 / 正脸半身 / 正脸全身 各 per 张，每类单独一张候选总图
        if a.closeup_min != 0.22:   # 特写 / 半身的分界
            SHOTS[0] = (*SHOTS[0][:2], a.closeup_min, SHOTS[0][3])
            SHOTS[1] = (*SHOTS[1][:3], a.closeup_min)
        per = {k: a.per for k, *_ in SHOTS}
        for kv in (a.per_shot or "").split(","):
            if "=" in kv:
                k, v = kv.split("=")
                per[k.strip()] = int(v)
        picked = pick_faces(video, per, t0=a.start, t1=a.end)
        for k, *_ in SHOTS:  # 清掉上一轮的同类产物，免得张数变少时残留旧图
            for f in [*out.glob(f"{k}_*.jpg"), *out.glob(f"frame_{k}_*.jpg")]:
                f.unlink()
        sheets, sheets43 = [], []
        for k, label, *_ in SHOTS:
            row, row43 = [], []
            for i, t in enumerate(picked[k], 1):
                t2 = clean_time(video, t) if a.avoid_subs else t
                img = grab_hd(video, t2, out) if a.sr else grab(video, t2)
                c, c43 = compose(img, a), compose(crop_ratio(img, 4 / 3), a)
                c.save(out / f"{k}_{i:02d}.jpg", quality=95)
                c43.save(out / f"{k}_{i:02d}_4x3.jpg", quality=95)
                img.save(out / f"frame_{k}_{i:02d}_{t2:.1f}s.jpg", quality=95)
                row.append(c)
                row43.append(c43)
                print(f"{k}_{i:02d}.jpg + 4x3  <- {t2:.1f}s（{label}）")
            if row:
                contact_sheet(row, cols=4).save(out / f"candidates_{k}.jpg", quality=92)
                contact_sheet(row43, cols=4).save(out / f"candidates_{k}_4x3.jpg", quality=92)
        print(f"候选总图: {out}/candidates_closeup|half|full(.jpg / _4x3.jpg)")
        return

    if a.image:
        frames = [(f"{Path(pth).stem}_{m}", load_image(pth, m, out)) for pth in a.image for m in a.fill]
    else:
        times = a.at if a.at else [t for t, _ in pick_frames(video, a.n, t0=a.start, t1=a.end)]
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
