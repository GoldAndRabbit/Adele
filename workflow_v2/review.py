# -*- coding: utf-8 -*-
"""
人工审核结果 review.json：每首歌一条 {status, cover, title, intro（歌曲介绍 + 演出介绍 + 歌词介绍，空行分开）, tags, note, fingerprint}。
通过时记下指纹（边界 + lyrics.ass + 选中的封面 + 标题）；之后这些有任何变化，通过自动失效（stale），hd 不会处理。
"""

import hashlib
import time

from .paths import read_json, write_json

STATUSES = ("pending", "approved", "rejected")


def load(c):
    return c.load("review") or {"songs": {}}


def segment_of(c, name):
    return next((s for s in (c.load("segments") or {}).get("items", []) if s["name"] == name), None)


def fingerprint(c, it, entry):
    d = c.song_dir(it)
    seg = segment_of(c, it["name"]) or {}
    h = hashlib.sha256()
    h.update(f"{seg.get('start')}|{seg.get('end')}|{entry.get('cover')}|{entry.get('title')}".encode())
    ass = d / "lyrics.ass"
    h.update(ass.read_bytes() if ass.exists() else b"-")
    return h.hexdigest()[:16]


def effective(c, it, entry):
    """approved 但内容在通过之后改过 -> stale。"""
    st = entry.get("status", "pending")
    if st == "approved" and entry.get("fingerprint") != fingerprint(c, it, entry):
        return "stale"
    return st


def save_entry(c, it, patch):
    rv = load(c)
    entry = rv["songs"].get(it["name"], {})
    entry.update({k: v for k, v in patch.items() if k in
                  ("status", "cover", "title", "intro", "tags", "note")})
    if "intro" in patch:   # 早先分两栏保存的介绍：合并之后不再用
        entry.pop("intro_song", None)
        entry.pop("intro_performance", None)
    if entry.get("status") not in STATUSES:
        entry["status"] = "pending"
    if patch.get("status") == "approved":
        if not entry.get("cover"):
            raise ValueError("先选一张封面再通过")
        if not (c.song_dir(it) / "lyrics.ass").exists():
            raise ValueError("还没有字幕（refine 没跑完），不能通过")
        entry["fingerprint"] = fingerprint(c, it, entry)
        entry["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    entry["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rv["songs"][it["name"]] = entry
    write_json(c.review, rv)
    return entry


def song_status(c, it):
    d = c.song_dir(it)
    seg = segment_of(c, it["name"])
    entry = load(c)["songs"].get(it["name"], {})
    info = read_json(d / "song.json", {})
    if (d / "post" / f"{it['name']} 4K60FPS Sub-WaterMark.mp4").exists():
        stage = "hd_done"
    elif (d / "covers").exists() and (d / "post_draft.json").exists():
        stage = "packaged"
    elif (d / "lyrics.ass").exists():
        stage = "refined"
    elif seg and seg.get("start") is not None:
        stage = "located"
    elif (d / "lyrics.txt").exists():
        stage = "lyrics"
    else:
        stage = "new"
    # 边界在精校之后被改过：字幕时间轴已经不对了，要重跑 refine
    sliced = info.get("slice")
    stale_refine = bool(seg and sliced and [round(seg["start"], 2), round(seg["end"], 2)] != sliced)
    span = f"{seg['start']:.0f}-{seg['end']:.0f}s" if seg and seg.get("start") is not None else ""
    return {"stage": stage, "review": effective(c, it, entry), "span": span, "needs_refine": stale_refine}
