# -*- coding: utf-8 -*-
"""
整场演唱会流程（单曲走 workflow/make_mv.py，见 skills/song-mv）。方案见 docs/design/concert_pipeline.md。

  new      建场次：concerts/<slug>/concert.json
  run      审核前的阶段，可 --from/--to 断点续跑：
             ingest    探测、抽字幕轨、整场 FLAC、无损 remux 成 mp4
             setlist   歌单（setlist.fm API 或 concerts/<slug>/setlist.txt）
             lyrics    逐首 Genius 歌词
             separate  整场人声分离
             segment   字幕轨 + 歌词定位每首歌，音频精修边界 -> segments.json
             refine    每首切音频 + 预览视频，跑字幕流程（workflow/song/：对齐 / 观众合唱 / 翻译 / 注释）-> subs/
             preview   每首切审核用的 720p 预览视频（前后多留 10s）-> preview.mp4
             package   候选封面 + 标题介绍
  serve    审核网页（http://127.0.0.1:8160）
  hd       只对审核通过的歌：成品（workflow/song/render.py：插帧 60fps -> 4K + 字幕 + logo / 水印 + FLAC）+ 封面 + 投稿信息
  status   各首状态

  .venv/bin/python -m workflow.live new shakira_madrid_2026 --source "~/Downloads/xxx.mkv" --artist Shakira \\
      --date 2026-10-03 --city Madrid --venue "Estadio Shakira" --tour "Las Mujeres Ya No Lloran World Tour"
  .venv/bin/python -m workflow.live run shakira_madrid_2026
  .venv/bin/python -m workflow.live run shakira_madrid_2026 --from refine --songs 8,9
"""

import argparse
import os
import subprocess
import sys
import time

from .paths import CONCERTS, ROOT, Concert, read_json, write_json

STAGES = ["ingest", "setlist", "lyrics", "separate", "segment", "refine", "preview", "package"]


def stage_fn(name):
    import importlib
    return getattr(importlib.import_module(f".{name}", __package__), f"stage_{name}")


def start_log(c, label):
    """输出同时写到 concerts/<slug>/logs/<时间>_<label>.log（含子进程）。"""
    c.logs.mkdir(parents=True, exist_ok=True)
    log = c.logs / f"{time.strftime('%Y%m%d-%H%M%S')}_{label}.log"
    tee = subprocess.Popen(["tee", "-a", str(log)], stdin=subprocess.PIPE)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(tee.stdin.fileno(), sys.stdout.fileno())
    os.dup2(tee.stdin.fileno(), sys.stderr.fileno())
    print(f"日志: {log}", flush=True)


def cmd_new(a):
    from .ingest import resolve_source
    c = Concert(a.slug)
    c.dir.mkdir(parents=True, exist_ok=True)
    info = read_json(c.info, {})
    info.update({k: v for k, v in {
        "slug": a.slug, "source_file": str(resolve_source(a.source)), "artist": a.artist, "artist_zh": a.artist_zh,
        "date": a.date,
        "city": a.city, "venue": a.venue, "tour": a.tour, "title": a.title, "setlist_url": a.setlist_url,
        "title_box": [int(x) for x in a.title_box.split(",")] if a.title_box else None,
        "cover_mask_bottom": a.cover_mask_bottom, "broadcast": a.broadcast,
    }.items() if v})
    write_json(c.info, info)
    print(f"写入 {c.info}")


def parse_songs(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def cmd_run(a):
    c = Concert(a.slug)
    if not c.info.exists():
        sys.exit(f"没有场次 {a.slug}，先 new")
    stages = STAGES[STAGES.index(a.from_): STAGES.index(a.to) + 1]
    start_log(c, f"{stages[0]}-{stages[-1]}")
    a.songs = parse_songs(a.songs)
    for s in stages:
        print(f"\n========== [{s}] ==========", flush=True)
        stage_fn(s)(c, a)


def cmd_hd(a):
    from .hd import run_hd
    c = Concert(a.slug)
    start_log(c, "hd")
    a.songs = parse_songs(a.songs)
    run_hd(c, a)


def cmd_status(a):
    from .review import song_status
    c = Concert(a.slug)
    for it in c.song_items():
        st = song_status(c, it)
        print(f"{it['idx']:>3} {it['title'][:34]:<34} {st['stage']:<10} {st['review']:<10} {st.get('span', '')}")


def cmd_serve(a):
    os.execv(str(ROOT / ".venv" / "bin" / "uvicorn"),
             ["uvicorn", "server.app:app", "--port", str(a.port), "--app-dir", str(ROOT)])


def main():
    p = argparse.ArgumentParser(prog="workflow.live", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="建场次")
    n.add_argument("slug")
    n.add_argument("--source", required=True, help="整场视频文件（或含视频的目录）")
    for k in ("artist", "artist-zh", "date", "city", "venue", "tour", "title"):
        n.add_argument(f"--{k}")
    n.add_argument("--setlist-url", help="setlist.fm 的这场歌单页（有 SETLISTFM_API_KEY 时用 API 读取）")
    n.add_argument("--title-box", help="转播画面上歌名字幕的位置 x,y,w,h（1080p 像素），如 Amazon 转播 40,976,660,56")
    n.add_argument("--cover-mask-bottom", type=float, help="封面底部模糊压暗的比例（盖台标/推广条），如 0.12")
    n.add_argument("--broadcast", help="转播信息，写介绍用，如 'Amazon Music / Prime Video 全球直播'")
    n.set_defaults(fn=cmd_new)

    r = sub.add_parser("run", help="审核前的阶段")
    r.add_argument("slug")
    r.add_argument("--from", dest="from_", choices=STAGES, default=STAGES[0])
    r.add_argument("--to", choices=STAGES, default=STAGES[-1])
    r.add_argument("--songs", help="只处理这些歌（序号或目录名，逗号分隔），lyrics/refine/package 有效")
    r.add_argument("--force", action="store_true", help="覆盖已有结果")
    r.set_defaults(fn=cmd_run)

    h = sub.add_parser("hd", help="只对审核通过的歌做高清")
    h.add_argument("slug")
    h.add_argument("--songs", help="只做这些歌（必须已通过审核）")
    h.add_argument("--dry-run", action="store_true", help="只列出会处理哪些歌")
    h.set_defaults(fn=cmd_hd)

    s = sub.add_parser("status")
    s.add_argument("slug")
    s.set_defaults(fn=cmd_status)

    v = sub.add_parser("serve", help="审核网页")
    v.add_argument("--port", type=int, default=8160)
    v.set_defaults(fn=cmd_serve)

    a = p.parse_args()
    CONCERTS.mkdir(exist_ok=True)
    a.fn(a)


if __name__ == "__main__":
    main()
