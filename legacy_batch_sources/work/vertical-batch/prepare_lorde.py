"""Finish the ten deferred Chile tracks after the current portrait batch and vocal restoration."""
import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pysubs2

from workflow.live.package import draft_meta
from workflow.live.paths import Concert, ROOT, VENV_PY, read_json, write_json
from workflow.live.refine import cut_audio
from workflow.vertical_cover import header_labels

base = Path(__file__).resolve().parent
c = Concert("lorde_lolla_chile2026")
items = [c.item(i) for i in (1, 3, 4, 5, 8, 9, 10, 12, 13, 17)]
segments = {r["name"]: r for r in c.load("segments")["items"]}
while not c.vocals.is_file() or (base / "PAUSED").exists():
    time.sleep(60)
rows = []
with (base / "queue.lock").open("a") as slot:
    fcntl.flock(slot, fcntl.LOCK_EX)
    for item in items:
        if (base / "PAUSED").exists():
            break
        directory = c.song_dir(item)
        seg = segments[item["name"]]
        status = base / "status" / (c.slug + "--" + item["name"] + ".json")
        try:
            write_json(status, dict(status="refining", title=item["title"]))
            changed = cut_audio(c, item, seg)
            if changed or not (directory / "subs/lyrics_poetic.ass").is_file():
                subprocess.run([str(VENV_PY), "-m", "workflow.song.run", "song", c.slug, item["name"]], cwd=ROOT, check=True)
            for name in ("lyrics.ass", "lyrics_literal.ass", "lyrics_poetic.ass"):
                subs = pysubs2.load(str(directory / "subs" / name))
                if not any(not e.is_comment and e.style == "Default" and e.plaintext.strip() for e in subs):
                    raise ValueError("字幕缺少有效歌词：" + name)
            draft_meta(c, item, seg, SimpleNamespace(force=False))
            labels = header_labels(c, item)
            rows.append(dict(concert=c.slug, name=item["name"], title=item["title"], sec=round(seg["end"]-seg["start"], 3)))
            write_json(status, dict(status="pending", title=item["title"], header=labels))
        except Exception as exc:
            write_json(status, dict(status="failed", title=item["title"], error=str(exc)))
            print("FAIL",item["name"],repr(exc),flush=True)
queue = base / "lorde-refined-queue.json"
write_json(queue, rows)
if rows and not (base / "PAUSED").exists():
    subprocess.run([sys.executable, str(base / "run.py"), "--queue-file", str(queue), "--wait-for-slot"], check=True)
