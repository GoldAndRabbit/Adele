# -*- coding: utf-8 -*-
"""
refine：逐首切音频 + 字幕。按 segments.json 从整场 audio.flac / vocals.wav 切出这首的片段（不切视频），
切审核用的预览视频，然后跑字幕流程（workflow.song.run：多遍识别 → 整首对齐 → 观众合唱检测 → 翻译 → 注释），
结果在歌曲目录的 subs/。字幕时间以片段起点为 0。

边界改了：重切音频，按旧时间轴算的缓存（节拍 / 音高 / 立体声）一起清掉，再重跑字幕流程；
识别缓存按音频内容记，不用清。
"""

import subprocess
import sys

from .paths import ROOT, VENV_PY, read_json, write_json
from .util import hms, run

# 按旧时间轴算的缓存：边界一改就对不上（Dai Dai 切掉开头 30 s 后没清，字幕流程用的切点整体错位 30 s）
TIMELINE_CACHES = ("beats.npy", "pitch.npz", "stereo.npz")


def selected(c, a):
    sel = set(a.songs) if getattr(a, "songs", None) else None
    segs = {s["name"]: s for s in (c.load("segments") or {}).get("items", [])}
    out = []
    for it in c.song_items():
        if sel and not ({it["name"], str(it["idx"]), f"{it['idx']:02d}"} & sel):
            continue
        seg = segs.get(it["name"])
        if not seg or seg.get("start") is None:
            print(f"{it['idx']:>2} {it['title']}: 没有定位（segments.json），跳过")
            continue
        if not (c.song_dir(it) / "lyrics.txt").exists():
            print(f"{it['idx']:>2} {it['title']}: 没有歌词，跳过")
            continue
        out.append((it, seg))
    return out


def cut_audio(c, it, seg, force=False):
    """片段边界变了就重切，并清掉按旧时间轴算的缓存（翻译缓存保留，不用重翻）。返回是否重切了。"""
    d = c.song_dir(it)
    info = read_json(d / "song.json", {})
    span = [round(seg["start"], 2), round(seg["end"], 2)]
    if info.get("slice") == span and (d / "audio.flac").exists() and (d / "vocals.wav").exists() and not force:
        return False
    (d / "reports").mkdir(parents=True, exist_ok=True)
    for f in TIMELINE_CACHES:
        (d / "reports" / f).unlink(missing_ok=True)
    trim = ["-ss", f"{span[0]:.3f}", "-to", f"{span[1]:.3f}"]
    run(["ffmpeg", "-v", "error", "-y", *trim, "-i", c.audio, "-c:a", "flac", "-ar", "48000", "-sample_fmt", "s32",
         d / "audio.flac"])
    run(["ffmpeg", "-v", "error", "-y", *trim, "-i", c.vocals, "-c:a", "pcm_s16le", d / "vocals.wav"])
    info["slice"] = span
    write_json(d / "song.json", info)
    return True


def sub_title(c, it):
    artist = read_json(c.info).get("artist", "")
    return f"《{it['title']}》 {artist}".strip()


def refine_one(c, it, seg, a):
    from .preview import make_preview
    d = c.song_dir(it)
    changed = cut_audio(c, it, seg, a.force)
    make_preview(c, it, seg)   # 边界改了预览视频也要跟着重切
    if not changed and not a.force and (d / "subs" / "lyrics_literal.ass").exists():
        print(f"{it['idx']:>2} {it['title']}: 已有字幕结果（边界没变；--force 重跑）", flush=True)
        return True
    log = d / "logs" / "v4_run.log"
    log.parent.mkdir(exist_ok=True)
    print(f"{it['idx']:>2} {it['title']}: 字幕流程开始（{hms(seg['start'])} - {hms(seg['end'])}，日志 {log}）", flush=True)
    with log.open("w") as fh:
        r = subprocess.run([str(VENV_PY), "-m", "workflow.song.run", "song", c.slug, it["name"]], cwd=ROOT,
                           stdout=fh, stderr=subprocess.STDOUT)
    print(f"{it['idx']:>2} {it['title']}: " + ("✓" if r.returncode == 0 else f"✗ 失败（exit {r.returncode}），见 {log}"), flush=True)
    return r.returncode == 0


def stage_refine(c, a):
    if not c.vocals.exists():
        sys.exit("缺少整场人声 vocals.wav，先跑 separate")
    todo = selected(c, a)
    bad = []
    for it, seg in todo:   # 一首一首跑：字幕流程里有本地模型（MMS），不并行
        try:
            ok = refine_one(c, it, seg, a)
        except Exception as e:  # noqa: BLE001 一首出错不影响其他歌
            print(f"{it['idx']:>2} {it['title']}: ✗ {type(e).__name__}: {e}", flush=True)
            ok = False
        if not ok:
            bad.append(it["title"])
    print(f"\nrefine：{len(todo) - len(bad)}/{len(todo)} 首完成" + (f"；失败：{', '.join(bad)}" if bad else ""))
