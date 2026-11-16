"""The standard project/song workflow and its sole batch coordinator."""
from datetime import datetime
import hashlib
from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil

from .paths import ROOT, Concert, read_json, write_json
from .stages import STAGES, perform
from workflow.delivery_config import products_ready, render_platforms, collection_platforms
from workflow.runtime import HostPool, locked


def selected_stages(first="source", last="covers"):
    if first not in STAGES or last not in STAGES or STAGES.index(first) > STAGES.index(last):
        raise ValueError("工作流起止模块无效")
    return list(STAGES[STAGES.index(first):STAGES.index(last) + 1])


def worker(task_path, host):
    """Subprocess boundary isolates render globals and model memory per song."""
    task_path = Path(task_path)
    task = read_json(task_path)
    concert = Concert(task["concert"])
    item = concert.item(task["song"])
    directory = concert.song_dir(item)
    state_path = task_path.parent / "result.json"
    record = {"concert": concert.slug, "song": item["name"], "host": host,
              "status": "running", "started_at": datetime.now().astimezone().isoformat(),
              "stages": {}, "task": str(task_path.resolve())}
    started = time.monotonic()
    with locked(directory / ".workflow-job.lock"):
        try:
            for stage in task["stages"]:
                stage_start = time.monotonic()
                record["stage"] = stage
                write_json(state_path, record)
                print(record["started_at"], host, concert.slug, item["name"], stage, flush=True)
                result = perform(stage, concert, item, task["options"], host) or {}
                record["stages"][stage] = {"elapsed_seconds": round(time.monotonic() - stage_start, 3), **result}
                if result.get("status") == "waiting_for_review":
                    record["status"] = "waiting_for_review"
                    break
            else:
                record["status"] = "ready"
        except (Exception, SystemExit) as error:
            record.update(status="failed", error=str(error))
            raise
        finally:
            record["finished_at"] = datetime.now().astimezone().isoformat()
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            write_json(state_path, record)
    return record


def existing_workers():
    """Find executing standard workers so a restarted coordinator can drain them."""
    active = {}
    for process in psutil.process_iter(["cmdline"]):
        args = process.info["cmdline"] or []
        if "-m" not in args or "--host" not in args:
            continue
        index = args.index("-m")
        if args[index:index + 3] != ["-m", "workflow.live", "worker"]:
            continue
        try:
            if Path(process.cwd()).resolve() != ROOT.resolve():
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        host = args[args.index("--host") + 1]
        if host in active:
            raise RuntimeError(f"同一机器已有多个存活任务：{host}")
        active[host] = process
    return active


def batch_tasks(config, batch, stages, options):
    """Read declarative jobs, including already-confirmed historical queues."""
    snapshot = read_json(batch / "priority_status.json", {})
    held = set(config.get("awaiting_user_review", []))
    blocked = config.get("blocked_jobs", {})
    projects = config.get("projects")
    if projects is None:
        slugs = list(dict.fromkeys([*config.get("concerts", []), *snapshot]))
        projects = [{"concert": slug, "songs": list(snapshot[slug]) if slug in snapshot else None}
                    for slug in slugs]
    jobs = []
    for project in projects:
        slug = project["concert"]
        if slug in held:
            continue
        concert = Concert(slug)
        names = project.get("songs")
        items = [concert.item(name) for name in names] if names is not None else concert.song_items()
        for item in items:
            key = slug + "/" + item["name"]
            if key in blocked:
                continue
            # Rendering an accepted queue never rechecks subtitles, artwork or
            # copy. The only inventory is whether selected finished files exist.
            if stages == ["delivery"] and products_ready(concert.song_dir(item), options.get("platforms")):
                snapshot.setdefault(slug, {})[item["name"]] = "delivered"
                continue
            jobs.append({"concert": slug, "song": item["name"], "stages": stages, "options": options})
    return jobs, snapshot


def write_collections(batch, config, snapshot):
    from workflow.bili_collection import storage_path
    groups = []
    for slug, songs in snapshot.items():
        concert = Concert(slug)
        metadata_path = storage_path(concert, slug)
        metadata = read_json(metadata_path, {})
        rows = []
        for name, status in songs.items():
            item = concert.item(name)
            directory = concert.song_dir(item)
            manifest = read_json(directory / "products/products.json", {})
            submission = read_json(directory / "delivery_bundle.json", {}).get("bilibili", {})
            ready = products_ready(directory, ["bilibili"])
            video = next((row for row in manifest.get("items", []) if row.get("platform") == "bilibili"
                          and row.get("status") == "ready"), {})
            rows.append({"name": name, "title": submission.get("合集显示名称") or item["title"],
                         "status": "ready" if ready else status if status != "delivered" else "available",
                         "input_video_path": str((directory / "products" / video["file"]).resolve()) if ready else None,
                         "run_id": manifest.get("run_id") if ready else None,
                         "files": [{**row, "path": str((directory / "products" / row["file"]).resolve())}
                                   for row in manifest.get("items", [])]})
        groups.append({"concert": slug, "platform": "bilibili", "tracks": rows,
                       "title": metadata.get("title"), "cover_path": metadata.get("cover_path"),
                       "metadata_path": str(metadata_path.resolve()),
                       "status": "ready" if rows and all(row["status"] == "ready" for row in rows) else "producing"})
    write_json(batch / "collections.json", {"platforms": list(collection_platforms()),
                                            "published": False, "collections": groups})


def run_batch(batch, stages, options, *, resume=False):
    batch = Path(batch).resolve()
    config = read_json(batch / "queue.json")
    if not isinstance(config, dict):
        raise ValueError("批次缺少声明式 queue.json")
    options = {**config.get("options", {}), **{k: v for k, v in options.items() if v is not None}}
    options["platforms"] = list(render_platforms(options.get("platforms") or config.get("render_platforms")))
    if "projects" not in config:
        # Old priority queues were explicitly accepted production selections.
        options["confirmed"] = True
    host = options.get("remote", config.get("remote"))
    hosts = ["local"] + ([host] if host else [])
    paused = batch / "PAUSED"
    if paused.exists() and not resume:
        return {"status": "paused", "completed": 0}
    status_file = batch / "workflow_status.json"
    mutex = threading.Lock()
    state = read_json(status_file, {})
    with locked(ROOT / "work/render-dispatch.lock"), locked(batch / "workflow.lock"):
        if resume:
            paused.unlink(missing_ok=True)
        (batch / "workflow.pid").write_text(str(__import__("os").getpid()))
        prefixes = [stage for stage in stages if stage in STAGES[:2]]
        prefix_failures = []
        if prefixes:
            projects = config.get("projects") or [{"concert": slug} for slug in config.get("concerts", [])]
            for project in projects:
                if project["concert"] in config.get("awaiting_user_review", []):
                    continue
                for stage in prefixes:
                    if paused.exists():
                        return {"status": "paused", "completed": 0}
                    key = project["concert"] + "/_project"
                    stage_start = time.monotonic()
                    state[key] = {"stage": stage, "status": "running", "host": "local",
                                  "started_at": datetime.now().astimezone().isoformat()}
                    write_json(status_file, state)
                    try:
                        with locked(HostPool().cache / "host-slots" / (hashlib.sha256(b"local").hexdigest()[:24] + ".lock")):
                            perform(stage, Concert(project["concert"]), None, options)
                        state[key]["status"] = "ready"
                    except (Exception, SystemExit) as error:
                        state[key].update(status="failed", error=str(error))
                        prefix_failures.append({"concert": project["concert"], "stage": stage, "error": str(error)})
                    finally:
                        state[key].update(elapsed_seconds=round(time.monotonic() - stage_start, 3),
                                          finished_at=datetime.now().astimezone().isoformat())
                        write_json(status_file, state)
                    if state[key]["status"] == "failed":
                        break
        stages = [stage for stage in stages if stage not in STAGES[:2]]
        if not stages:
            return {"status": "incomplete" if prefix_failures else "ready", "completed": 0, "failures": prefix_failures}
        if prefix_failures:
            config = {**config, "awaiting_user_review": [*config.get("awaiting_user_review", []),
                                                         *(row["concert"] for row in prefix_failures)]}
        jobs, snapshot = batch_tasks(config, batch, stages, options)
        adopted = existing_workers()
        preferences = config.get("preferred_machine", {})

        def execute(task, host):
            old = adopted.pop(host, None)
            while old is not None:
                try:
                    if not old.is_running() or old.status() == psutil.STATUS_ZOMBIE:
                        break
                except psutil.NoSuchProcess:
                    break
                # The other Mac continues working while this worker is adopted.
                time.sleep(1)
            if paused.exists():
                return {"status": "paused"}
            key = task["concert"] + "/" + task["song"]
            folder = batch / "jobs" / hashlib.sha256(key.encode()).hexdigest()[:24]
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "task.json"
            (folder / "result.json").unlink(missing_ok=True)
            write_json(path, task)
            started = datetime.now().astimezone().isoformat()
            with mutex:
                state[key] = {"status": "running", "host": host, "started_at": started,
                              "stages": stages, "log": str(folder / "worker.log")}
                write_json(status_file, state)
            args = [sys.executable, "-u", "-m", "workflow.live", "worker", str(path), "--host", host]
            with (folder / "worker.log").open("a", buffering=1) as log:
                result = subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            record = read_json(folder / "result.json", {})
            if result.returncode != 0:
                record.update(status="failed", error=record.get("error") or f"worker exit {result.returncode}")
            with mutex:
                state[key] = {**state[key], **record}
                if stages == ["delivery"]:
                    directory = Concert(task["concert"]).song_dir(Concert(task["concert"]).item(task["song"]))
                    snapshot.setdefault(task["concert"], {})[task["song"]] = (
                        "delivered" if products_ready(directory, options["platforms"]) else "available")
                    write_json(batch / "priority_status.json", snapshot)
                    write_collections(batch, config, snapshot)
                write_json(status_file, state)
            if record.get("status") == "failed":
                raise RuntimeError(record["error"])
            return record

        def eligible(task, host):
            preferred = preferences.get(task["concert"] + "/" + task["song"])
            if preferred and preferred != host:
                return False
            # A remote cover requires its installed FIBO runtime configuration.
            return not (host != "local" and "covers" in stages and not options.get("cover_remote_config"))

        results, pending = HostPool(hosts, paused=paused.exists).run(jobs, execute, eligible=eligible)
        write_json(batch / "priority_status.json", snapshot)
        if stages == ["delivery"]:
            write_collections(batch, config, snapshot)
        outcome = {"status": "paused" if paused.exists() else "incomplete" if pending or prefix_failures or any(
            row["status"] == "failed" or row.get("value", {}).get("status") == "waiting_for_review"
            for row in results) else "ready", "completed": sum(
                row["status"] == "ready" and row.get("value", {}).get("status") == "ready"
                for row in results), "pending": len(pending),
            "failures": prefix_failures + [row for row in results if row["status"] == "failed"]}
        write_json(batch / "workflow_result.json", outcome)
        return outcome


def run_project(concert, stages, options):
    batch = concert.dir / "workflow"
    batch.mkdir(exist_ok=True)
    songs = options.get("songs")
    if (batch / "PAUSED").exists() and not options.get("resume"):
        return {"status": "paused", "completed": 0}
    # The song catalog may not exist until the split module has run.
    project = {"concert": concert.slug, "songs": songs}
    write_json(batch / "queue.json", {"projects": [project]})
    return run_batch(batch, stages, options, resume=options.get("resume", False))
