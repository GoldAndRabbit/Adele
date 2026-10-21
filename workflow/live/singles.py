# -*- coding: utf-8 -*-
"""
把单曲（posts/<name>/）挂到审核页上：虚拟场次 concerts/singles/，每首歌一个目录，
里面放软链接（字幕结果 subs/、候选封面 covers/、成品 post/、水印计划）、720p 预览视频，
和从 posts/<name>/post/<name>.json 同步过来的投稿信息（post_draft.json，改了投稿 json 后再跑一次就同步）。
posts/<name>/ 下的文件一个都不改。按歌名合并：只处理传进来的歌，审核页上已有的其他单曲保留。

    .venv/bin/python -m workflow.live.singles lose_yourself_2009 sara_perche_1983 ...
"""

import json
import subprocess
import sys

from .paths import CONCERTS, ROOT, read_json, write_json

SLUG = "singles"


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
    if not (c / "concert.json").exists():
        write_json(c / "concert.json", {"slug": SLUG, "title": "单曲", "artist": "", "date": ""})
    items = {x["name"]: x for x in (read_json(c / "setlist.json") or {}).get("items", [])}
    segs = {x["name"]: x for x in (read_json(c / "segments.json") or {}).get("items", [])}
    for name in names:
        p = ROOT / "posts" / name
        post = json.loads((p / "post" / f"{name}.json").read_text())
        song = post.get("song") or {}
        d = c / "songs" / name
        d.mkdir(parents=True, exist_ok=True)
        dur = round(duration(p / "source.mp4"), 2)   # 和 segments.json 同样精度，否则总览会误报「边界改过」
        for old in ("lyrics.ass", "exp_v3", "exp_v4"):   # 早期链过的，现在不用了
            if (d / old).is_symlink():
                (d / old).unlink()
        for sub in ("covers", "subs", "post"):
            link(d / sub, p / sub)
        link(d / "watermark.json", p / "watermark.json")   # 中间水印计划（workflow/song/watermark.py）
        # 预览：整首 720p（硬件编码，几十秒）
        if not (d / "preview.mp4").exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p / "source.mp4"), "-vf", "scale=-2:720",
                            "-c:v", "h264_videotoolbox", "-b:v", "3500k", "-c:a", "aac", "-b:a", "160k",
                            str(d / "preview.mp4")], check=True)
        write_json(d / "song.json", {"lang": "", "langs": [], "preview": [0.0, dur], "slice": [0.0, dur],
                                     "genius_urls": []})
        write_json(d / "post_draft.json", {"title": post.get("title"), "tags": post.get("tags", []),
                                           "intro": post.get("intro", {}), "song": song})
        items[name] = {"idx": items.get(name, {}).get("idx") or len(items) + 1, "name": name,
                       "title": song.get("title") or name, "kind": "song",
                       "artist": song.get("artist"), "notes": (post.get("performance") or {}).get("event")}
        segs[name] = {"name": name, "start": 0.0, "end": round(dur, 2), "confidence": 1.0}
        print(f"{name}: {dur:.0f}s", flush=True)
    order = sorted(items.values(), key=lambda x: x["idx"])
    write_json(c / "setlist.json", {"source": "posts", "items": order})
    write_json(c / "segments.json", {"items": [segs[x["name"]] for x in order if x["name"] in segs], "gaps": []})


if __name__ == "__main__":
    build(sys.argv[1:])
