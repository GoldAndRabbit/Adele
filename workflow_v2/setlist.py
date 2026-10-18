# -*- coding: utf-8 -*-
"""
setlist：歌单 -> setlist.json。以 concerts/<slug>/setlist.txt 为准（可手改）：
  - 设置了 SETLISTFM_API_KEY 且 concert.json 有 setlist_url 时，从 setlist.fm API 生成 setlist.txt（已存在不覆盖，--force 重拉）
  - 否则手写 setlist.txt（setlist.fm 网页对脚本有反爬，不抓网页）

setlist.txt 每行一项（# 开头是注释）：
  标题 | 查歌词用的歌手（空 = 本场艺人） | 备注 | genius=<歌词页>（可选）
  [tape] 开头的是过场（预录视频），不出成品；串烧写成「A / B」并在备注里写 medley
"""

import os
import re
import sys

import requests

from .paths import read_json, slugify, write_json

API = "https://api.setlist.fm/rest/1.0/setlist/{}"


def from_api(c, url):
    from llm import load_env
    load_env()
    key = os.environ.get("SETLISTFM_API_KEY")
    if not key or not url:
        return None
    sid = re.search(r"-([0-9a-f]{6,10})\.html", url)
    if not sid:
        print(f"认不出 setlist.fm 链接里的 id：{url}")
        return None
    r = requests.get(API.format(sid[1]), headers={"x-api-key": key, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    d = r.json()
    artist = d.get("artist", {}).get("name", "")
    lines = [f"# 来源: {url}", "# 标题 | 查歌词用的歌手 | 备注 | genius=<url>"]
    for part in d.get("sets", {}).get("set", []):
        if part.get("encore"):
            lines.append("# encore")
        for s in part.get("song", []):
            name, info = s.get("name", "").strip(), (s.get("info") or "").strip()
            who = (s.get("cover") or {}).get("name") or ""
            guest = (s.get("with") or {}).get("name")
            notes = "; ".join(x for x in [info, f"with {guest}" if guest else ""] if x)
            prefix = "[tape] " if s.get("tape") else ""
            lines.append(f"{prefix}{name} | {who if who != artist else ''} | {notes}".rstrip(" |"))
    return "\n".join(lines) + "\n"


def parse(text, artist):
    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind = "song"
        if line.lower().startswith("[tape]"):
            kind, line = "interlude", line[6:].strip()
        cols = [x.strip() for x in line.split("|")]
        title = cols[0]
        who = cols[1] if len(cols) > 1 and cols[1] else artist
        notes = cols[2] if len(cols) > 2 else ""
        genius = next((x.split("=", 1)[1] for x in cols[3:] if x.startswith("genius=")), None)
        medley = "medley" in notes.lower() and " / " in title
        idx = len(items) + 1
        items.append({
            "idx": idx, "name": f"{idx:02d}_{slugify(title)}", "title": title, "artist": who, "kind": kind,
            "parts": [x.strip() for x in title.split(" / ")] if medley else [title],
            "notes": notes, "genius_url": genius,
        })
    return items


def stage_setlist(c, a):
    info = read_json(c.info)
    if a.force or not c.setlist_txt.exists():
        text = from_api(c, info.get("setlist_url"))
        if text:
            c.setlist_txt.write_text(text, encoding="utf-8")
            print(f"setlist.fm API -> {c.setlist_txt}")
    if not c.setlist_txt.exists():
        sys.exit(f"缺少歌单：设置 SETLISTFM_API_KEY（.env）并在 concert.json 填 setlist_url，或手写 {c.setlist_txt}\n"
                 + __doc__.split("setlist.txt 每行一项")[1])
    items = parse(c.setlist_txt.read_text(encoding="utf-8"), info.get("artist", ""))
    write_json(c.setlist, {"source": info.get("setlist_url"), "items": items})
    songs = [it for it in items if it["kind"] == "song"]
    print(f"歌单 {len(items)} 项：歌曲 {len(songs)}，过场 {len(items) - len(songs)}")
    for it in items:
        print(f"  {it['idx']:>2} {'  ' if it['kind'] == 'song' else '~ '}{it['title']}"
              + (f"  [{it['notes']}]" if it["notes"] else ""))
