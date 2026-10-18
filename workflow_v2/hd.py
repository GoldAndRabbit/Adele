# -*- coding: utf-8 -*-
"""
hd：唯一会切视频、抽帧的步骤，只处理审核通过（且通过后没再改过）的歌，一首做完再做下一首：
  1) v1 make_mv.py --from interp --to render（--start/--end 从整场 source.mp4 切出 1080p 片段 -> RIFE 60fps ->
     4K + 烧 lyrics.ass + 水印 logo + 片段 FLAC 48k/24bit），--clean-frames：渲染完立即删帧
  2) 选中的候选封面（已高清化）-> post/cover/cover_01.jpg / cover_01_4x3.jpg
  3) 审核页里改过的标题 / 介绍 / 标签 -> post/<name>.json
"""

import os
import shutil
import subprocess
import sys

from . import review
from .package import cover_candidates
from .paths import ROOT, VENV_PY, read_json, write_json
from .util import hms, run

JPG_FRAME = 0.6e6  # 1080p JPEG(q1) 一帧大约 0.6MB，磁盘预检用


def approved(c, a):
    rv = review.load(c)
    sel = set(a.songs) if a.songs else None
    out, skipped = [], []
    for it in c.song_items():
        if sel and not ({it["name"], str(it["idx"]), f"{it['idx']:02d}"} & sel):
            continue
        entry = rv["songs"].get(it["name"], {})
        st = review.effective(c, it, entry)
        if st == "approved":
            out.append((it, entry))
        elif sel or st == "stale":
            skipped.append((it, st))
    return out, skipped


def check_disk(c, seg, fps):
    need = (seg["end"] - seg["start"]) * (fps + 60) * JPG_FRAME * 1.3 + 3e9
    free = shutil.disk_usage(c.dir).free
    if free < need:
        sys.exit(f"磁盘不够：这首至少要 {need / 1e9:.0f}GB（帧序列 + 成品），剩余 {free / 1e9:.0f}GB。清理后重跑，已完成的会跳过")


def write_post(c, it, entry, video):
    d = c.song_dir(it)
    draft = read_json(d / "post_draft.json", {})
    post = d / "post"
    out = dict(draft)
    out.update({
        "name": it["name"],
        "title": entry.get("title") or draft.get("title"),
        "intro": entry.get("intro") or draft.get("intro_text")
                 or "\n\n".join(x for x in (draft.get("intro", {}).get("song"), draft.get("intro", {}).get("performance")) if x),
        "tags": entry.get("tags") or draft.get("tags", []),
        "spec": {"resolution": "3840x2160", "fps": 60, "audio": "FLAC 48kHz/24bit (Hi-Res)"},
        "files": {"video": str(video.relative_to(ROOT)), "cover": str((post / "cover" / "cover_01.jpg").relative_to(ROOT)),
                  "cover_4x3": str((post / "cover" / "cover_01_4x3.jpg").relative_to(ROOT)),
                  "subtitle": str((d / "lyrics.ass").relative_to(ROOT))},
        "source": {"concert": read_json(c.info).get("title"), "segment": [review.segment_of(c, it["name"])[k] for k in ("start", "end")]},
    })
    write_json(post / f"{it['name']}.json", out)


def hd_one(c, it, entry, a):
    d = c.song_dir(it)
    seg = review.segment_of(c, it["name"])
    info = read_json(d / "song.json", {})
    if info.get("slice") != [round(seg["start"], 2), round(seg["end"], 2)]:
        print(f"{it['idx']:>2} {it['title']}: 片段音频和边界对不上（边界改过但没重跑 refine），跳过")
        return False
    video = d / "post" / f"{it['name']} 4K60FPS Sub-WaterMark.mp4"
    print(f"\n========== {it['idx']:>2} {it['title']}  {hms(seg['start'])} - {hms(seg['end'])} ==========", flush=True)
    if not video.exists():
        check_disk(c, seg, read_json(c.info).get("fps", 30))
        src = d / "source.mp4"
        if not src.exists():
            src.symlink_to(c.source)
        env = dict(os.environ, ADELE_POSTS=str(c.songs))
        cmd = [VENV_PY, ROOT / "workflow" / "make_mv.py", "--name", it["name"], "--from", "interp", "--to", "render",
               "--start", f"{seg['start']:.3f}", "--end", f"{seg['end']:.3f}", "--clean-frames"]
        if a.fast:
            cmd.append("--fast")
        run(cmd, env=env)
        (d / "video_1080.mp4").unlink(missing_ok=True)  # 随时能从源重建，不占盘
    # 候选封面已经是高清化后的成品：选中的那张直接拷成 cover_01（16:9）/ cover_01_4x3
    cand = next((x for x in cover_candidates(d) if x["id"] == entry["cover"]), None)
    if cand:
        (d / "post" / "cover").mkdir(parents=True, exist_ok=True)
        shutil.copy(d / cand["file"], d / "post" / "cover" / "cover_01.jpg")
        if cand["file_4x3"]:
            shutil.copy(d / cand["file_4x3"], d / "post" / "cover" / "cover_01_4x3.jpg")
    write_post(c, it, entry, video)
    print(f">>> {video}")
    return True


def run_hd(c, a):
    todo, skipped = approved(c, a)
    for it, st in skipped:
        print(f"跳过 {it['idx']:>2} {it['title']}：审核状态 {st}" + ("（通过后内容改过，需要重新审核）" if st == "stale" else ""))
    if not todo:
        print("没有审核通过的歌，不做任何处理")
        return
    print(f"将处理 {len(todo)} 首：" + "、".join(it["title"] for it, _ in todo))
    if a.dry_run:
        return
    a.force = False
    done = [it["title"] for it, entry in todo if hd_one(c, it, entry, a)]
    print(f"\nhd：{len(done)}/{len(todo)} 首完成")
