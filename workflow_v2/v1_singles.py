# -*- coding: utf-8 -*-
"""
把 v1 单曲（posts/<name>/）挂到审核页上：建一个虚拟场次 concerts/v1_singles/，每首歌一个目录，
里面只放软链接（原字幕 lyrics.ass、v1 实验 exp/、v2 实验 exp_v2/、新样式封面 exp/covers/）和一个 720p 预览视频，
posts/<name>/ 下原来的文件一个都不改。

    .venv/bin/python -m workflow_v2.v1_singles lose_yourself_2009 sara_perche_1983 ...
"""

import json
import subprocess
import sys

from .paths import CONCERTS, ROOT, write_json

SLUG = "v1_singles"


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def link(dst, src):
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(src)


def build(names):
    c = CONCERTS / SLUG
    (c / "songs").mkdir(parents=True, exist_ok=True)
    write_json(c / "concert.json", {"slug": SLUG, "title": "v1 单曲（新流程对比）", "artist": "", "date": ""})
    items, segs = [], []
    for i, name in enumerate(names, 1):
        p = ROOT / "posts" / name
        post = json.loads((p / "post" / f"{name}.json").read_text())
        song = post.get("song") or {}
        d = c / "songs" / name
        (d / "exp").mkdir(parents=True, exist_ok=True)
        dur = round(duration(p / "source.mp4"), 2)   # 和 segments.json 同样精度，否则总览会误报「边界改过」
        # 原流程字幕、新流程结果、新样式封面：软链接
        link(d / "lyrics.ass", p / "lyrics.ass")
        for f in ("lines.json", "lyrics.ass", "lyrics.srt"):
            link(d / "exp" / f, p / "exp" / f)
        link(d / "covers", p / "exp" / "covers")
        link(d / "exp_v2", p / "exp_v2")   # v2 实验（align4.py）整个目录
        # 预览：整首 720p（硬件编码，几十秒）
        if not (d / "preview.mp4").exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p / "source.mp4"), "-vf", "scale=-2:720",
                            "-c:v", "h264_videotoolbox", "-b:v", "3500k", "-c:a", "aac", "-b:a", "160k",
                            str(d / "preview.mp4")], check=True)
        write_json(d / "song.json", {"lang": "", "langs": [], "preview": [0.0, dur], "slice": [0.0, dur],
                                     "genius_urls": []})
        write_json(d / "post_draft.json", {"title": post.get("title"), "tags": post.get("tags", []),
                                           "intro": post.get("intro", {}), "song": song})
        items.append({"idx": i, "name": name, "title": song.get("title") or name, "kind": "song",
                      "artist": song.get("artist"), "notes": (post.get("performance") or {}).get("event")})
        segs.append({"name": name, "start": 0.0, "end": round(dur, 2), "confidence": 1.0})
        print(f"{name}: {dur:.0f}s", flush=True)
    write_json(c / "setlist.json", {"source": "v1 posts", "items": items})
    write_json(c / "segments.json", {"items": segs, "gaps": []})


if __name__ == "__main__":
    build(sys.argv[1:])
