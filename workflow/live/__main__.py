"""One workflow: source, split, subtitles, posting, preview, covers, delivery.

See docs/workflow.md for project setup, local/dual-Mac runs and pause/resume.
"""
import argparse
import json
import os
from pathlib import Path
from .paths import ROOT, Concert, read_json, write_json
from .pipeline import run_batch, run_project, selected_stages, worker
from .stages import STAGES


def create(args):
    if not args.slug or not all(c.isalnum() or c in "_-" for c in args.slug):
        raise ValueError("项目名只能包含字母、数字、下划线和连字符")
    concert = Concert(args.slug)
    concert.dir.mkdir(parents=True, exist_ok=True)
    info = read_json(concert.info, {})
    if args.source:
        from .ingest import resolve_source
        info["source_file"] = str(resolve_source(args.source).resolve())
    fields = {"slug": args.slug, "input_kind": args.kind, "source_url": args.url,
              "artist": args.artist, "artist_zh": args.artist_zh,
              "date": args.date, "city": args.city, "venue": args.venue,
              "tour": args.tour, "title": args.title, "title_zh": args.title,
              "title_en": args.title_en, "song_title": args.song_title,
              "setlist_url": args.setlist_url, "broadcast": args.broadcast}
    info.update({key: value for key, value in fields.items() if value is not None})
    if args.start is not None or args.end is not None:
        if args.end is None or args.end <= (args.start or 0):
            raise ValueError("截取范围需要有效的 --start / --end 秒数")
        info["source_slice"] = [args.start or 0, args.end]
    if args.title_box:
        info["title_box"] = [int(value) for value in args.title_box.split(",")]
    write_json(concert.info, info)
    print(concert.info)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="workflow.live", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="登记演唱会或单曲输入")
    new.add_argument("slug")
    source = new.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", help="本地原片或视频目录")
    source.add_argument("--url", help="视频链接")
    new.add_argument("--kind", choices=["concert", "single"], default="concert")
    for name in ("artist", "artist-zh", "date", "city", "venue", "tour", "title", "title-en", "song-title", "setlist-url", "broadcast", "title-box"):
        new.add_argument("--" + name)
    new.add_argument("--start", type=float)
    new.add_argument("--end", type=float)
    run = commands.add_parser("run", help="运行标准模块；默认到封面，不自动做成品或投稿")
    run.add_argument("slug", nargs="?")
    run.add_argument("--batch", type=Path)
    run.add_argument("--from", dest="first", choices=STAGES, default="source")
    run.add_argument("--to", choices=STAGES, default="covers")
    run.add_argument("--songs", help="目录名或序号，逗号分隔")
    run.add_argument("--platforms", nargs="+", choices=["bilibili", "douyin"])
    machines = run.add_mutually_exclusive_group()
    machines.add_argument("--remote", help="SSH 用户@地址；默认读取第二台 Mac 配置")
    machines.add_argument("--local", action="store_true")
    for name in ("key", "model", "cover-remote-config", "browser", "proxy", "url"):
        run.add_argument("--" + name)
    for name in ("auto-review", "replace-covers", "confirmed", "force"):
        run.add_argument("--" + name, action="store_true", default=None)
    run.add_argument("--resume", action="store_true", help="清除暂停，接续未完成任务")
    run.add_argument("--dry-run", action="store_true", help="只显示模块与任务，不处理素材")
    pause = commands.add_parser("pause", help="当前歌曲收尾，停止后续派工")
    pause.add_argument("batch", type=Path)
    status = commands.add_parser("status", help="读取项目或批次状态")
    status.add_argument("path")
    serve = commands.add_parser("serve", help="本地审稿页")
    serve.add_argument("--port", type=int, default=8160)
    internal = commands.add_parser("worker", help="内部单曲执行器，由统一调度器调用")
    internal.add_argument("task", type=Path)
    internal.add_argument("--host", required=True)
    args = parser.parse_args(argv)
    if args.command == "new":
        create(args)
    elif args.command == "worker":
        worker(args.task, args.host)
    elif args.command == "pause":
        if not args.batch.is_dir():
            parser.error("批次目录不存在")
        write_json(args.batch / "PAUSED", {"mode": "drain_current_only"})
        print("当前歌曲收尾后暂停")
    elif args.command == "serve":
        os.execv(str(ROOT / ".venv/bin/uvicorn"), ["uvicorn", "server.app:app", "--port", str(args.port), "--app-dir", str(ROOT)])
    elif args.command == "status":
        path = Path(args.path)
        if not path.is_dir():
            path = Concert(args.path).dir / "workflow"
        print(json.dumps(read_json(path / "workflow_status.json", {}), ensure_ascii=False, indent=2))
    else:
        if bool(args.slug) == bool(args.batch):
            parser.error("指定项目名或 --batch，两者不能同时指定")
        stages = selected_stages(args.first, args.to)
        defaults = read_json(ROOT / "delivery_defaults.json", {}).get("worker", {})
        options = {key: value for key, value in vars(args).items()
                   if key not in {"command", "slug", "batch", "first", "to", "dry_run", "local"}}
        options["remote"] = "" if args.local else args.remote or (read_json(args.batch / "queue.json", {}).get("remote") if args.batch else None) or defaults.get("remote")
        options["key"] = args.key or defaults.get("key", "~/.ssh/adele_render_worker")
        options["model"] = args.model or defaults.get("model")
        options["cover_remote_config"] = args.cover_remote_config or defaults.get("cover_remote_config")
        options["songs"] = args.songs.split(",") if args.songs else None
        if args.dry_run:
            from .pipeline import batch_tasks
            if args.batch:
                jobs, _ = batch_tasks(read_json(args.batch / "queue.json"), args.batch, stages, options)
            else:
                concert = Concert(args.slug)
                jobs = [{"concert": concert.slug, "song": item["name"]} for item in concert.song_items()]
            print(json.dumps({"stages": stages, "options": options, "jobs": jobs}, ensure_ascii=False, indent=2))
            return
        from workflow.runtime import awake
        with awake():
            result = (run_batch(args.batch, stages, options, resume=args.resume) if args.batch
                      else run_project(Concert(args.slug), stages, options))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == "incomplete":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
