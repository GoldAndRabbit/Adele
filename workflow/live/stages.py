"""Seven standard modules. These functions never start their own song queue."""
from argparse import Namespace
from pathlib import Path
import subprocess
import sys

from .paths import ROOT, VENV_PY, read_json, write_json
from workflow.sources import ensure_selection

STAGES = ("source", "split", "subtitles", "posting", "preview", "covers", "delivery")


def source(concert, options):
    from .ingest import stage_ingest
    info = read_json(concert.info)
    if info.get("source_url") and not Path(info.get("source_file") or "").is_file():
        from workflow.download import stage_download
        folder = concert.dir / "download"
        folder.mkdir(exist_ok=True)
        args = Namespace(url=info["source_url"], proxy=options.get("proxy"),
                         cookies_from_browser=options.get("browser"), cookies=options.get("cookies"),
                         no_source_subs=False)
        stage_download(args, folder)
        info["source_file"] = str((folder / "source.mp4").resolve())
        write_json(concert.info, info)
    stage_ingest(concert, Namespace(force=options.get("force", False)))


def split(concert, options):
    from . import setlist, lyrics, segment
    args = Namespace(force=options.get("force", False), songs=options.get("songs"))
    info = read_json(concert.info)
    if info.get("input_kind") == "single":
        from .paths import slugify
        title = info.get("song_title")
        if not title:
            raise ValueError("单曲必须登记原文歌名 --song-title")
        if not concert.setlist.is_file():
            item = {"idx": 1, "name": "01_" + slugify(title), "title": title,
                    "artist": info["artist"], "kind": "song", "parts": [title], "notes": ""}
            write_json(concert.setlist, {"source": "single", "items": [item]})
        lyrics.stage_lyrics(concert, args)
        if not concert.segments.is_file():
            span = info.get("source_slice") or [0, info["duration"]]
            write_json(concert.segments, {"items": [dict(item, start=span[0], end=span[1],
                          confidence=1.0) for item in concert.song_items()], "gaps": []})
    else:
        setlist.stage_setlist(concert, args)
        lyrics.stage_lyrics(concert, args)
        # Existing confirmed segmentation is reusable; don't reload a full-show
        # separator just because a later preparation module is being resumed.
        if not concert.segments.is_file() or args.force:
            segment.stage_segment(concert, args)
    for item in concert.song_items():
        directory = concert.song_dir(item)
        segment_row = next((row for row in read_json(concert.segments)["items"]
                            if row["name"] == item["name"]), None)
        if segment_row and segment_row.get("start") is not None:
            song = read_json(directory / "song.json", {})
            song.setdefault("slice", [segment_row["start"], segment_row["end"]])
            write_json(directory / "song.json", song)
            ensure_selection(concert, item)


def subtitles(concert, item, options, host):
    """Reuse a matching subtitle result, otherwise process this one song only."""
    from workflow.preparation import prepare_audio, remote_subtitles
    from workflow.song.run import run_song
    from workflow.paths import render_subtitle
    directory = concert.song_dir(item)
    policy = ensure_selection(concert, item)
    identity = {"source": policy["source"], "slice": policy["slice"]}
    unchanged = read_json(directory / "audio_source.json") == identity
    if not options.get("force") and unchanged and render_subtitle(directory).is_file():
        return
    if host != "local":
        return remote_subtitles(concert, item, host=host, key=options.get("key"), force=options.get("force", False))
    prepare_audio(concert, item, host=host, key=options.get("key"),
                  force=options.get("force", False))
    run_song(concert.slug, item["name"])


def posting(concert, item, options, host):
    from .package import draft_meta, validate_presentation
    from workflow.delivery_bundle import write_bundle
    from workflow.song.title_translation import resolved
    directory = concert.song_dir(item)
    if not resolved(directory):
        # The translation module owns its cache and manual title overrides.
        subprocess.run([str(VENV_PY), '-m', 'workflow.song.title_translation', str(directory)], cwd=ROOT, check=True)
    policy = ensure_selection(concert, item)
    draft_meta(concert, item, dict(start=policy["slice"][0], end=policy["slice"][1]),
               Namespace(force=options.get("force", False)))
    validate_presentation(concert, item)
    bundle = write_bundle(concert, item)
    from workflow.templates import posting_issues
    issues = posting_issues(bundle["bilibili"])
    if issues:
        # Preserve manual wording and continue preparing previews/covers; mark
        # the final copy for review instead of reporting the draft as ready.
        return {"status": "needs_review", "issues": issues}


def preview(concert, item, options, host):
    from workflow.preview import enable_browser
    ensure_selection(concert, item)
    enable_browser(concert, item)


def covers(concert, item, options, host):
    from workflow import covers as cover_stage
    from workflow.ai_cover import reviewed_revision
    from workflow.fibo_reference import reselect
    directory = concert.song_dir(item)
    if reviewed_revision(directory / "covers/ai") and not options.get("replace_covers"):
        from workflow.delivery_bundle import sync_cover_release
        sync_cover_release(concert, item)
        return
    model = options.get("model")
    if not model:
        raise ValueError("生成新封面需要 --model；已有发布封面直接复用")
    ensure_selection(concert, item)
    preview(concert, item, options, host)
    if item["name"] not in read_json(concert.dir / "fibo-cover-plan.json", {}):
        reselect(concert, item)
    folder = directory / "workflow/covers"
    folder.mkdir(parents=True, exist_ok=True)
    queue = folder / "queue.json"
    write_json(queue, [{"slug": concert.slug, "name": item["name"]}])
    cover_stage.run(queue, Path(model), remote_config=options.get("cover_remote_config"),
                    url=options.get("url", "http://127.0.0.1:8160"),
                    auto_review=options.get("auto_review", False),
                    replace_existing=options.get("replace_covers", False), executor_host=host)
    status = read_json(folder / "dual-cover-status.json", {})[concert.slug + "/" + item["name"]]
    if status["status"] == "needs_repair":
        raise RuntimeError(status.get("error") or "封面生成失败")
    if status["status"] not in {"released", "released_verified"}:
        return {"status": "waiting_for_review", "cover": status}


def delivery(concert, item, options, host):
    from workflow.delivery_config import products_ready
    from workflow.delivery_bundle import write_bundle
    from workflow import delivery as producer
    from datetime import datetime
    from uuid import uuid4
    if not options.get("confirmed"):
        from . import review
        entry = review.load(concert).get("songs", {}).get(item["name"], {})
        if review.effective(concert, item, entry) != "approved":
            return {"status": "waiting_for_review"}
    if products_ready(concert.song_dir(item), options.get("platforms")):
        write_bundle(concert, item)
        return {"status": "reused"}
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
    remote = (producer.Remote(host, Path(options.get("key") or "~/.ssh/adele_render_worker"), run_id)
              if host != "local" else None)
    producer.run(concert, remote, run_id, [item["name"]], platforms=options.get("platforms"))


def perform(stage, concert, item, options, host="local"):
    # Legacy alignment helpers use imports relative to workflow/. Keep the path
    # setup at the standard worker boundary instead of in dated batch scripts.
    sys.path.insert(0, str(ROOT / "workflow"))
    if stage not in STAGES:
        raise ValueError(f"未知工作流模块 {stage}")
    function = globals()[stage]
    if stage in STAGES[:2]:
        return function(concert, options)
    return function(concert, item, options, host)
