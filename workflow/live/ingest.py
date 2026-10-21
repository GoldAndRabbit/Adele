# -*- coding: utf-8 -*-
"""ingest：探测源文件、抽内嵌字幕轨、整场音频转 FLAC 48k/24bit、整文件无损 remux 成 mp4（不切、不转码视频）。"""

import json
import subprocess
from pathlib import Path

from .paths import read_json, write_json
from .util import run


def ffprobe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                          "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def resolve_source(path):
    """有的发布包是「同名目录/同名.mkv」，给目录也能找到里面的视频。"""
    p = Path(path).expanduser()
    if p.is_dir():
        vids = sorted(x for x in p.iterdir() if x.suffix.lower() in {".mkv", ".mp4", ".mov", ".ts"} and x.is_file())
        if not vids:
            raise SystemExit(f"{p} 里没有视频文件")
        p = max(vids, key=lambda x: x.stat().st_size)
    if not p.exists():
        raise SystemExit(f"找不到源文件 {p}")
    return p


def stage_ingest(c, a):
    info = read_json(c.info)
    src = Path(info["source_file"])
    d = ffprobe(src)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    au = next(s for s in d["streams"] if s["codec_type"] == "audio")
    subs = [s for s in d["streams"] if s["codec_type"] == "subtitle"]
    num, den = v["r_frame_rate"].split("/")
    info.update({
        "duration": float(d["format"]["duration"]), "fps": float(num) / float(den), "fps_str": v["r_frame_rate"],
        "width": v["width"], "height": v["height"], "video_codec": v["codec_name"],
        "audio_codec": au["codec_name"], "audio_rate": int(au.get("sample_rate", 0)), "audio_channels": au.get("channels"),
        "has_captions": bool(subs),
    })
    write_json(c.info, info)
    print(f"源: {src.name}\n  {info['width']}x{info['height']} @ {info['fps_str']}，{info['duration'] / 60:.1f} 分钟，"
          f"音频 {info['audio_codec']} {info['audio_rate']}Hz，字幕轨 {len(subs)} 条")
    if info["audio_rate"] and info["audio_rate"] < 48000:
        print(f"  注意：源音频只有 {info['audio_rate']}Hz，成品 FLAC 48k/24bit 是重采样")

    if subs and not c.captions.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", f"0:{subs[0]['index']}", c.captions])
    if not c.audio.exists():
        tmp = c.audio.with_suffix(".partial.flac")
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", f"0:{au['index']}", "-vn",
             "-c:a", "flac", "-ar", "48000", "-sample_fmt", "s32", tmp])
        tmp.replace(c.audio)
    if not c.source.exists():
        if src.suffix.lower() == ".mp4":
            c.source.symlink_to(src)
        else:
            # 浏览器播不了 mkv；-c copy 只换封装，画面音频一个字节不动，faststart 便于网页拖动
            tmp = c.source.with_suffix(".partial.mp4")
            run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", f"0:{v['index']}", "-map", f"0:{au['index']}",
                 "-c", "copy", "-movflags", "+faststart", tmp])
            tmp.replace(c.source)
    print(f"ingest 完成: {c.dir}")
