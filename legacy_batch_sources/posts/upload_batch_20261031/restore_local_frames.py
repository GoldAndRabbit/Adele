"""Restore existing external frame links to verified local files before resuming RIFE."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, signal, json, time, hashlib, shutil, fcntl

B = Path(__file__).parent
W = B.parent / '.local-render' / 'olivia_tiny_desk2023_jmh3iruf4ra'
PID = 29748
lock = (B / 'restore_local.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
state = {'pid': os.getpid(), 'status': 'restoring', 'restored_files': 0, 'restored_bytes': 0}

def save():
    state['at'] = time.time()
    (B / 'restore_local_status.json').write_text(json.dumps(state, indent=2) + '\n')

def copy_local(p):
    source = p.resolve()
    before = source.stat()
    tmp = p.with_suffix('.local-copy')
    h = hashlib.sha256()
    with source.open('rb') as src, tmp.open('wb') as dst:
        for data in iter(lambda: src.read(4 * 1024**2), b''):
            dst.write(data)
            h.update(data)
    verify = hashlib.sha256()
    with tmp.open('rb') as src:
        for data in iter(lambda: src.read(4 * 1024**2), b''):
            verify.update(data)
    assert tmp.stat().st_size == before.st_size and h.digest() == verify.digest()
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    tmp.replace(p)
    return before.st_size

try:
    os.kill(PID, signal.SIGSTOP)
    files = [p for kind in ['frames_in', 'frames_out'] for p in (W/kind).glob('*.jpg')
             if p.stem.isdigit() and p.is_symlink()]
    state['total_files'] = len(files)
    save()
    # Bound concurrent reads, keeping all producer writes and final frame files local.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(files), 16):
            if shutil.disk_usage(W).free < 8 * 1024**3:
                raise RuntimeError('Local free space below 8 GiB; producer stays paused')
            for future in as_completed([pool.submit(copy_local, p) for p in files[start:start+16]]):
                state['restored_bytes'] += future.result()
                state['restored_files'] += 1
            save()
    outputs = list((W/'frames_out').glob('[0-9]*.jpg'))
    sizes = [p.stat().st_size for p in outputs if p.stat().st_size > 1000]
    remaining = max(0, 65706 - len(sizes))
    estimate = remaining * (sum(sizes) / max(1, len(sizes))) * 1.2 + 6 * 1024**3
    state.update(required_free_bytes=round(estimate), free_bytes=shutil.disk_usage(W).free)
    if state['free_bytes'] < estimate:
        raise RuntimeError('Insufficient local space for remaining frames; producer stays paused')
    os.kill(PID, signal.SIGCONT)
    state['status'] = 'complete_producer_resumed'
except Exception as exc:
    state.update(status='blocked', reason=str(exc))
finally:
    save()
