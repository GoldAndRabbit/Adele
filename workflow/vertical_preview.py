"""Render review-only portrait clips. Run with a concert slug and optional song ID."""

import argparse
import concurrent.futures
import subprocess
import sys
import tempfile
from pathlib import Path

import pysubs2

from workflow.live.paths import Concert, ROOT, read_json
from workflow.vertical_cover import header_labels, original_source


def render(concert, item, force, full=False):
    directory = concert.song_dir(item)
    info = read_json(directory / "song.json")
    song = read_json(directory / "post_draft.json", {}).get("song", {})
    labels = header_labels(concert, item)
    captions = next((directory / "subs" / name for name in
                     ("lyrics_poetic.ass", "lyrics_literal.ass", "lyrics.ass")
                     if (directory / "subs" / name).is_file()), None)
    if not captions:
        raise ValueError("缺少精校字幕")
    from workflow.portrait_browser import preview_data
    header = preview_data(concert, item, directory)["header_text"]
    from workflow.vertical_source import prepare as prepare_source
    ts_source = prepare_source(concert, item)
    source = ts_source or directory / "preview.mp4"
    begin, end = info["slice"]
    duration = end - begin
    start_ms = 0
    if not full:
        first = next((event.start for event in pysubs2.load(str(captions))
                      if event.style == "Default" and event.end > event.start
                      and not event.is_comment and not event.plaintext.startswith("《")), 0)
        duration = min(60, duration)
        start_ms = max(0, min(first, round((end - begin - duration) * 1000)))
    if ts_source:
        seek = start_ms / 1000
    elif source.is_file():
        seek = begin - info["preview"][0] + start_ms / 1000
    else:
        source = original_source(concert, item)
        seek = begin + start_ms / 1000
    folder = directory / "vertical"
    folder.mkdir(exist_ok=True)
    output = folder / ("full.mp4" if full else f"preview-{start_ms}.mp4")
    settings_path = concert.dir / "vertical_preview.json"
    dependencies = [source, captions, settings_path, concert.dir / "vertical_source.json", directory / "song.json", concert.info, Path(__file__),
                    ROOT / "workflow/portrait_style.json", directory / "title_translation.json", ROOT / "workflow/portrait_browser.py",
                    ROOT / "workflow/portrait_header.py", ROOT / "workflow/portrait_title.py", ROOT / "workflow/vertical_cover.py", ROOT / "workflow/vertical.py", directory / "post_draft.json", directory / "watermark.json",
                    directory / "content_box.json", ROOT / "assets/adele-logo.png"]
    if not force and output.exists() and all(
        output.stat().st_mtime >= path.stat().st_mtime for path in dependencies if path.exists()
    ):
        return
    # Publish the new file only after ffmpeg finishes; an existing player can keep reading.
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        pending = Path(temp) / output.name
        subprocess.run([
            sys.executable, "-m", "workflow.vertical", str(source), str(pending),
            "--captions", str(captions), "--start", str(seek), "--caption-start", str(start_ms / 1000),
            "--duration", str(duration), "--song-directory", str(directory), "--song", song.get("title_song") or item["title"],
            "--fps", str(info.get("vertical_preview_fps", 50 if ts_source else 30)),
            "--song-zh", header["song_zh"],
            "--en", labels["en"],
            "--zh", labels["zh"],
            "--intro", labels["event"],
        ], cwd=ROOT, check=True)
        pending.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("concert")
    parser.add_argument("song", nargs="?")
    parser.add_argument("--full", action="store_true", help="Render the complete song slice")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    concert = Concert(args.concert)
    items = [concert.item(args.song)] if args.song else concert.song_items()
    if not items:
        parser.error("场次没有曲目")
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {pool.submit(render, concert, item, args.force, args.full): item["name"] for item in items}
        for job in concurrent.futures.as_completed(jobs):
            name = jobs[job]
            try:
                job.result()
                print(f"就绪 {name}", flush=True)
            except Exception as error:
                failed.append(name)
                print(f"失败 {name}: {error}", file=sys.stderr, flush=True)
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
