"""Timestamped publishing filenames; keep internal frame IDs and review history stable."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import os
import errno
import re

from workflow.live.paths import ROOT, read_json

SHANGHAI = ZoneInfo("Asia/Shanghai")


def cover_path(directory, source, platform, ratio):
    if not source:
        return None
    path = ROOT / source
    if not path.is_file():
        return None
    path = path.resolve()
    exports = (directory / "covers/posting").resolve()
    if path.is_relative_to(exports) and re.fullmatch(
        rf"{platform}_ai_{ratio}_\d{{10}}", path.stem
    ):
        return str(path)
    stat = path.stat()
    stamp = datetime.fromtimestamp(stat.st_mtime, SHANGHAI).strftime("%y%m%d%H%M")
    # Different revisions can be generated within the same minute. Give each
    # a distinct directory so the user-facing basename remains exact.
    revision = hashlib.sha256(os.fsencode(path) + f":{stat.st_ino}:{stat.st_mtime_ns}".encode()).hexdigest()[:20]
    target = exports / revision / f"{platform}_ai_{ratio}_{stamp}{path.suffix.lower()}"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, target)
        except FileExistsError:
            pass
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            try:
                target.symlink_to(path)
            except FileExistsError:
                pass
    return str(target)


def active_cover_set(directory):
    """Return the first complete four-cover release in active master order."""
    # Use four finished exports from the same active master, even during a regeneration.
    ai = directory / "covers/ai"
    variants = read_json(ai / "variants.json", [])
    required = {("bili-ai", "16x9"), ("bili-ai", "4x3"), ("douyin-ai", "3x4"), ("douyin-ai", "4x3")}
    for master in read_json(ai / "masters.json", []):
        files = {(row["platform"], row["ratio"]): (ai / row["file"]).resolve()
                 for row in variants if row["master"] == master["file"]}
        if required <= files.keys() and all(files[key].is_file() for key in required):
            return files
    return {}
