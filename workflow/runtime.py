"""Shared execution primitives for every standard workflow stage.

One consumer per Mac takes the next eligible song from a shared queue. A pause
stops claims, never interrupts an executing song. Host locks are shared by cover,
subtitle and delivery jobs, including coordinators in different processes.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path
import threading
import time

from workflow.live.paths import read_json, write_json

CACHE = Path.home() / "Library/Caches/adele"


@contextmanager
def locked(path, *, shared=False, blocking=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | (0 if blocking else fcntl.LOCK_NB))
        yield


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024**2), b""):
            result.update(block)
    return result.hexdigest()


def source_digest(source, cache=None):
    """Read an unchanged original once; identity changes invalidate the cache."""
    source = Path(source)

    def identity():
        stat = source.stat()
        return [str(source.resolve()), stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns, stat.st_ctime_ns]

    version = identity()
    key = hashlib.sha256(json.dumps(version).encode()).hexdigest()
    folder = (Path(cache) if cache is not None else CACHE) / "source-sha256"
    folder.mkdir(parents=True, exist_ok=True)
    # Wait for the other consumer's checksum instead of reading the same HDD twice.
    with (folder / (key + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = read_json(folder / (key + ".json"), {})
        if saved.get("identity") == version and identity() == version:
            return saved["sha256"]
        digest = sha(source)
        if identity() != version:
            raise RuntimeError("校验期间原片发生变化，停止当前曲目")
        write_json(folder / (key + ".json"), {"identity": version, "sha256": digest})
        return digest


class HostPool:
    """A single scheduling policy shared by all heavy song-level stages.

    execute(job, host) runs synchronously until that song has finished or failed.
    The caller persists business status; this class owns claims and host slots.
    A busy host is skipped while other hosts continue draining eligible work.
    """

    def __init__(self, hosts=("local",), *, paused=lambda: False, cache=None):
        self.hosts = tuple(dict.fromkeys(hosts))
        if not self.hosts:
            raise ValueError("至少需要一台执行机器")
        self.paused = paused
        self.cache = Path(cache) if cache is not None else CACHE

    def run(self, jobs, execute, *, eligible=lambda job, host: True, on_error=None):
        pending = list(jobs)
        results = []
        mutex = threading.Lock()

        def consume(host):
            key = hashlib.sha256(host.encode()).hexdigest()[:24]
            try:
                slot = locked(self.cache / "host-slots" / (key + ".lock"))
                slot.__enter__()
            except BlockingIOError:
                return
            try:
                while True:
                    with mutex:
                        if self.paused():
                            return
                        index = next((i for i, job in enumerate(pending)
                                      if eligible(job, host)), None)
                        if index is None:
                            return
                        job = pending.pop(index)
                    started = time.monotonic()
                    try:
                        value = execute(job, host)
                        row = {"job": job, "host": host, "status": "ready", "value": value}
                    except Exception as error:
                        row = {"job": job, "host": host, "status": "failed", "error": str(error)}
                        if on_error:
                            on_error(job, host, error)
                    row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    with mutex:
                        results.append(row)
            finally:
                slot.__exit__(None, None, None)

        with ThreadPoolExecutor(max_workers=len(self.hosts)) as pool:
            list(pool.map(consume, self.hosts))
        return results, pending
