"""Enroll the Mexico set only after the existing download produces the complete A/V source."""
import json
import os
from pathlib import Path
import subprocess
import time

from workflow.live.paths import Concert, read_json, write_json
from workflow.storage import archive_root

base = Path(__file__).resolve().parent
concert = Concert("dualipa_mexico2025")
archive = archive_root() / "sources/concerts" / concert.slug
info = concert.load("info")
choices = [Path(info["source_file"]), concert.source, archive / "source.mp4", archive / "source.mkv", archive / "source.webm"]

def tail_decodes(path, duration):
    # Decode a three-second window near EOF, requiring real payload for both streams.
    seek = max(0, duration - 4)
    common = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-ss", str(seek), "-i", str(path), "-t", "3"]
    for output, minimum in [
        (["-map", "0:v:0", "-vf", "fps=2,scale=2:2", "-pix_fmt", "gray", "-f", "rawvideo"], 4 * 4),
        (["-map", "0:a:0", "-ar", "8000", "-ac", "1", "-f", "s16le"], 2 * 8000 * 2),
    ]:
        result = subprocess.run([*common, *output, "-"], capture_output=True)
        if result.returncode or len(result.stdout) < minimum:
            return False
    return True


def complete(path):
    if not path.is_file():
        return False
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                           capture_output=True, text=True)
    if probe.returncode:
        return False
    data = json.loads(probe.stdout)
    streams = data.get("streams", [])
    for kind in ("audio", "video"):
        if not any(s.get("codec_type") == kind for s in streams):
            return False
    duration = float(data["format"].get("duration") or 0)
    return abs(duration - info["duration"]) < 2 and tail_decodes(path, duration)

def enroll(source):
    if not concert.source.is_file() and source != concert.source:
        if concert.source.is_symlink():
            temp = concert.source.with_name(".source-intake.tmp")
            temp.symlink_to(source.resolve())
            os.replace(temp, concert.source)
        else:
            concert.source.symlink_to(source.resolve())
    rows = read_json(base / "queue.json")
    keys = {(r["concert"], r["name"]) for r in rows}
    added = 0
    for item in concert.song_items():
        if item.get("review_hidden") or (concert.slug, item["name"]) in keys:
            continue
        song = concert.song_dir(item)
        start, end = read_json(song / "song.json")["slice"]
        rows.append(dict(group=info["title"], concert=concert.slug, name=item["name"], title=item["title"],
                         source=str(source.resolve()), sec=round(end-start,3), preview=(song/"preview.mp4").is_file(),
                         sub=(song/"subs/lyrics.ass").is_file(), draft=(song/"post_draft.json").is_file(),
                         full=(song/"vertical/full.mp4").is_file(), covers=len(read_json(song/"vertical/candidates.json",[]))))
        added += 1
    if added:
        write_json(base / "queue.json", rows)
    print(f"Verified {source}; enrolled {added} tracks", flush=True)

if __name__ == "__main__":
    while True:
        if not (base / "PAUSED").exists():
            source = next((p for p in choices if complete(p)), None)
            if source:
                enroll(source)
                break
        time.sleep(60)
