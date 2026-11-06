"""Prepare the explicitly selected broadcast source for portrait review."""
import fcntl
import subprocess
import tempfile
from pathlib import Path

from workflow.live.paths import read_json, write_json
from workflow.vertical_cover import cover_ffmpeg


def _publish(concert, item, output):
    folder = concert.song_dir(item) / "vertical"
    folder.mkdir(parents=True, exist_ok=True)
    link = folder / "original-selected.mp4"
    if not link.is_file() or link.resolve() != output.resolve():
        pending = folder / "original-selected.pending"
        pending.unlink(missing_ok=True)
        pending.symlink_to(output.resolve())
        pending.replace(link)
    return output


def prepare(concert, item):
    policy = read_json(concert.dir / "vertical_source.json", {})
    if not policy:
        return None
    selection = policy["songs"].get(item["name"])
    if not selection:
        raise ValueError("尚未确认当前片源的曲目起止点")
    source = Path(selection.get("source", policy["source"]))
    if not source.is_file():
        raise FileNotFoundError("工作流指定的原片未挂载，不回退其他片源")
    directory = Path(selection["directory"])
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "source.mp4"
    expected = {"source": str(source), "mtime": source.stat().st_mtime_ns, "slice": selection["slice"]}
    marker = directory / "source.json"
    with (directory / ".source.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if output.is_file() and read_json(marker) == expected:
            return _publish(concert, item, output)
        start, end = selection["slice"]
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            pending = Path(temporary) / "source.mp4"
            subprocess.run([
                cover_ffmpeg(), "-nostdin", "-v", "error", "-i", str(source),
                "-ss", str(start), "-t", str(end-start), "-map", "0:v:0", "-map", "0:a:0",
                *(["-vf", "bwdif=mode=send_field:parity=tff:deint=all", "-r", "50"]
                  if selection.get("kind", "ts") == "ts" else []),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(pending),
            ], check=True)
            pending.replace(output)
            write_json(marker, expected)
    return _publish(concert, item, output)
