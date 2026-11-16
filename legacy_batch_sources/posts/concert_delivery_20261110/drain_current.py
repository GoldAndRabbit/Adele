import fcntl
import os
from pathlib import Path
import subprocess
import time
from workflow.live.paths import Concert, read_json, write_json

base = Path(__file__).resolve().parent
c = Concert("dualipa_mexico2025")
locks = []
active = []
for item in c.song_items():
    directory = c.song_dir(item)
    record = read_json(directory/"render_status.json", {})
    if record.get("status") == "running":
        active.append(item["name"])
    elif record.get("status") == "queued":
        handle = (directory/"render.lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        except BlockingIOError:
            active.append(item["name"])
write_json(base/"pause_status.json", {"status":"draining", "active":active,"protected":len(locks)})
while "workflow.concert_delivery dualipa_mexico2025" in subprocess.run(["ps","-p","8153","-o","command="],capture_output=True,text=True).stdout:
    time.sleep(5)
results = {n:read_json(c.dir/"songs"/n/"render_status.json",{}).get("status") for n in active}
write_json(base/"pause_status.json",{"status":"paused","results":results})
