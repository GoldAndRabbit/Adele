# -*- coding: utf-8 -*-
"""画面上下 / 左右的黑边（宽银幕演唱会：4K 画面里实际内容只有 3840×1600，上下各 280 黑边）。

左上角 logo、歌曲中间的水印都要放在画面内容里，不放在黑边上。
结果是内容区域占整个画面的比例 {"x", "y", "w", "h"}（和分辨率无关：预览 720p、成品 4K 都能用），
缓存在歌曲目录的 content_box.json。

    .venv/bin/python workflow/letterbox.py posts/dualipa_mexico2025/11_electricity
"""

import json
import re
import subprocess
import sys
from pathlib import Path

FULL = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
SAMPLES = 6        # 歌曲里均匀取几段，每段 10 s
MIN_BAR = 0.02     # 黑边小于画面 2% 当作没有（压缩噪声、片源本身的细边）


def _duration(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def detect(video, t0=None, t1=None):
    """ffmpeg cropdetect：每段取最后稳定的结果，几段取并集（某段画面暗，cropdetect 会多裁，取最大的内容区域）。
    t0 / t1：只看这一段（整场演唱会里的一首）。"""
    t0 = t0 or 0.0
    dur = (t1 if t1 is not None else _duration(video)) - t0
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip().split(",")
    W, H = int(size[0]), int(size[1])
    boxes = []
    for k in range(SAMPLES):
        t = t0 + dur * (k + 0.5) / SAMPLES
        err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{max(0, t - 5):.2f}", "-i", str(video), "-t", "10",
                              "-vf", "fps=2,cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
        if m:
            w, h, x, y = map(int, m[-1])
            boxes.append((x, y, x + w, y + h))
    if not boxes:
        return dict(FULL)
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    # 很窄的边当作没有；上下 / 左右按对称处理（片源黑边都是居中的）
    top = min(y0, H - y1) / H
    side = min(x0, W - x1) / W
    top = top if top >= MIN_BAR else 0.0
    side = side if side >= MIN_BAR else 0.0
    return {"x": round(side, 4), "y": round(top, 4), "w": round(1 - 2 * side, 4), "h": round(1 - 2 * top, 4)}


def content_box(d):
    """歌曲目录的内容区域（有缓存读缓存）。视频用 preview.mp4，没有就 source.mp4；都没有当作没黑边。"""
    d = Path(d)
    f = d / "content_box.json"
    if f.exists():
        return json.loads(f.read_text())
    video = next((d / n for n in ("preview.mp4", "source.mp4") if (d / n).exists()), None)
    if video is None:
        return dict(FULL)
    box = detect(video)
    f.write_text(json.dumps(box) + "\n")
    return box


if __name__ == "__main__":
    for p in sys.argv[1:]:
        (Path(p) / "content_box.json").unlink(missing_ok=True)
        print(p, content_box(p))
