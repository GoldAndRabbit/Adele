"""Drain available dual-platform masters in concert priority order on two Macs."""
import os
import psutil
import subprocess
import sys
import time
from pathlib import Path

from workflow.concert_delivery import locked
from workflow.live.paths import ROOT, Concert, read_json, write_json
from workflow.delivery_config import collection_platforms, products_ready, render_platforms

HERE = ROOT / "posts/concert_delivery_20261110"
PRIORITY = ["dualipa_mexico2025", "olivia_acl_lclxvyamuce", "shakira_madrid_2026"]
HOST = "zhaojing@192.168.3.10"


def current_state(slug, name, platforms=None):
    """This batch is already approved. Only inspect finished products."""
    return "delivered" if products_ready(Concert(slug).songs / name, platforms) else "available"


def existing_workers():
    """Adopt in-flight single-song coordinators after a scheduler restart."""
    active = {}
    prefix = ["-m", "workflow.concert_delivery"]
    for proc in psutil.process_iter(["cmdline"]):
        args = proc.info["cmdline"] or []
        if "--single-worker" not in args or "-m" not in args:
            continue
        i = args.index("-m")
        if args[i:i+2] != prefix or "--only" not in args:
            continue
        try:
            if Path(proc.cwd()).resolve() != ROOT.resolve():
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        machine = args[args.index("--remote")+1] if "--remote" in args else "local"
        if machine in active:
            raise RuntimeError(f"检测到重复制作进程：{machine}")
        task = (args[i+2], args[args.index("--only")+1])
        print("接管在制任务", machine, *task, proc.pid, flush=True)
        active[machine] = task, proc
    return active


def write_collections(batch, config, snapshot):
    """Keep a local collection delivery list; creating this file never publishes."""
    from workflow.bili_collection import storage_path
    collections = []
    for slug in config.get('concerts', []):
        c = Concert(slug)
        metadata = read_json(storage_path(c, slug), {})
        tracks = []
        for item in c.song_items():
            directory = c.song_dir(item)
            manifest = read_json(directory / 'products/products.json', {})
            ready = products_ready(directory, ['bilibili'])
            video = next((row for row in manifest.get('items', [])
                          if row.get('platform') == 'bilibili' and row.get('status') == 'ready'), {})
            tracks.append({'name': item['name'], 'title': item['title'],
                           'status': 'ready' if ready else snapshot.get(slug, {}).get(item['name'], 'available'),
                           'input_video_path': str((directory / 'products' / video['file']).resolve()) if ready else None,
                           'run_id': manifest.get('run_id') if ready else None})
        collections.append({'concert': slug, 'platform': 'bilibili', 'metadata_path': str(storage_path(c, slug).resolve()),
                            'title': metadata.get('title'), 'cover_path': metadata.get('cover_path'),
                            'status': 'ready' if tracks and all(t['status'] == 'ready' for t in tracks) else 'producing',
                            'tracks': tracks})
    write_json(batch / 'collections.json', {'platforms': list(collection_platforms()),
               'published': False, 'collections': collections})


def schedule(batch=HERE):
    status_path = batch / "priority_status.json"
    config = read_json(batch / "queue.json")
    selected = render_platforms(config.get("render_platforms"))
    host = config.get("remote", HOST)
    active = existing_workers()
    retry_after = {}
    held = set(config.get("awaiting_user_review", []))
    snapshot = read_json(status_path, {})
    if not snapshot:
        raise RuntimeError("已确认的制作队列为空")
    write_collections(batch, config, snapshot)
    while True:
        dirty = False
        for machine, (task, child) in list(active.items()):
            if isinstance(child, psutil.Process):
                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    continue
            elif child.poll() is None:
                continue
            slug, name = task
            state = current_state(slug, name, selected)
            snapshot.setdefault(slug, {})[name] = state
            if state != "delivered":
                retry_after[task] = time.monotonic() + max(30,config.get('retry_cooldown_seconds',3600))
            del active[machine]
            dirty = True
        if dirty:
            write_json(status_path, snapshot)
            write_collections(batch, config, snapshot)
        if (batch / "PAUSED").exists():
            if not active:
                return
            time.sleep(1)
            continue

        if len(active) < 2:
            config = read_json(batch / "queue.json")
            # Newly authorized concerts can join without interrupting either
            # executing song. Only add new jobs; retain in-memory completions.
            added = False
            for slug in config.get('concerts', []):
                if slug not in snapshot:
                    c = Concert(slug)
                    snapshot[slug] = {item['name']: current_state(slug, item['name'], selected)
                                      for item in c.song_items()}
                    added = True
            if added:
                write_json(status_path, snapshot)
                write_collections(batch, config, snapshot)
            held = set(config.get("awaiting_user_review", []))
            blocked = config.get("blocked_jobs", {})
            busy = {task for task, _ in active.values()}
            preferences = config.get("preferred_machine", {})
            available = [(slug, name) for slug, rows in snapshot.items() if slug not in held
                             for name, state in rows.items() if state == "available"
                             and f"{slug}/{name}" not in blocked
                             and (slug, name) not in busy
                             and time.monotonic() >= retry_after.get((slug, name), 0)]
            for machine in ("local", host):
                if machine in active or (batch / "PAUSED").exists():
                    continue
                task = next((task for task in available if task not in busy
                             and preferences.get("/".join(task), machine) == machine), None)
                if task is None:
                    continue
                busy.add(task)
                slug, name = task
                args = [sys.executable, "-u", "-m", "workflow.concert_delivery", slug,
                        "--single-worker", "--only", name, "--platforms", *selected]
                if machine != "local":
                    args.extend(["--remote", machine])
                active[machine] = task, subprocess.Popen(args, cwd=ROOT)
                print(time.strftime("%F %T"), machine, slug, name, flush=True)
        if not active:
            if all(state == "delivered" for rows in snapshot.values() for state in rows.values()):
                return
            time.sleep(30)
        else:
            time.sleep(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, default=HERE)
    args = parser.parse_args()
    with locked(ROOT / 'work/render-dispatch.lock'), locked(args.batch / "priority.lock"):
        (args.batch / "priority.pid").write_text(str(os.getpid()))
        schedule(args.batch)
