"""Consume newly enrolled Mexico rows after the current batch releases the production slot."""
import subprocess
import sys
import time
from pathlib import Path

from workflow.live.paths import read_json

base = Path(__file__).resolve().parent
slug = "dualipa_mexico2025"
while True:
    rows = [r for r in read_json(base / "queue.json") if r["concert"] == slug]
    if len(rows) == 22 and not (base / "PAUSED").exists():
        result = subprocess.run([sys.executable, str(base / "run.py"), "--concert", slug, "--wait-for-slot"])
        if (base / "PAUSED").exists():
            time.sleep(60)
            continue
        result.check_returncode()
        break
    time.sleep(60)
