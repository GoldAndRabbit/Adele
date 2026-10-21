# -*- coding: utf-8 -*-
"""
审核用的单曲预览视频 songs/<nn>/preview.mp4：从 source.mp4 精确切出（重新编码，帧级准确），720p 小码率，
前后各多留 PAD 秒，方便在审核页上把边界往外调。和高清成品无关（高清在 hd 阶段从源重新切）。
song.json 里记下 preview = [预览起点, 预览终点]（整场时间），网页据此换算：整场时间 = 预览起点 + 播放时间。
"""

from .paths import read_json, write_json
from .util import run

PAD = 10.0


def make_preview(c, it, seg, force=False):
    d = c.song_dir(it)
    info = read_json(d / "song.json", {})
    dur = read_json(c.info).get("duration") or seg["end"] + PAD
    want = [round(max(0.0, seg["start"] - PAD), 2), round(min(dur, seg["end"] + PAD), 2)]
    out = d / "preview.mp4"
    if out.exists() and info.get("preview") == want and not force:
        return False
    tmp = d / "preview.partial.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{want[0]:.3f}", "-to", f"{want[1]:.3f}", "-i", c.source,
         "-vf", "scale=1280:-2", "-c:v", "h264_videotoolbox", "-b:v", "3500k", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", tmp])
    tmp.replace(out)
    info = read_json(d / "song.json", {})
    info["preview"] = want
    write_json(d / "song.json", info)
    return True


def stage_preview(c, a):
    from concurrent.futures import ThreadPoolExecutor
    from .refine import selected
    todo = selected(c, a)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda x: make_preview(c, *x, a.force), todo))
    print(f"preview：{len(todo)} 首")
