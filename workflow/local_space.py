"""Preflight for the local finalization staging area; never removes source assets."""
import json, shutil
from pathlib import Path

def prepare(root, work, info):
    staging = root / 'posts/.local-render'
    if work.parent.resolve() != staging.resolve():
        return
    freed = 0
    for d in (root / 'posts').iterdir():
        receipt = d / 'post/publish.json'
        if not receipt.is_file() or not (d / 'source.mp4').exists():
            continue
        try:
            if not json.loads(receipt.read_text()).get('bvid'):
                continue
        except (ValueError, OSError):
            continue
        cached = staging / d.name
        if cached != work and cached.is_dir() and not cached.is_symlink():
            freed += sum(p.stat().st_size for p in cached.rglob('*') if p.is_file() and not p.is_symlink())
            shutil.rmtree(cached)
        intermediate = d / 'video_1080.mp4'
        if intermediate.is_file() and not intermediate.is_symlink():
            freed += intermediate.stat().st_size
            intermediate.unlink()
    # Reserve input JPEGs, RIFE output JPEGs and 8 GiB for final encoding/copy.
    needed = int(info['duration'] * (60 * 1.35 + info['fps'] * .25) * 1024**2 + 8 * 1024**3)
    free = shutil.disk_usage(work).free
    report = {'free_bytes': free, 'estimated_required_bytes': needed, 'cleaned_bytes': freed}
    (work / 'space_preflight.json').write_text(json.dumps(report, indent=2))
    print(f'Local space preflight: free={free/1024**3:.1f} GiB, estimated={needed/1024**3:.1f} GiB, cleaned={freed/1024**3:.1f} GiB', flush=True)
    if free < needed:
        raise RuntimeError(f'Insufficient local space before interpolation: {free/1024**3:.1f} GiB available, {needed/1024**3:.1f} GiB estimated')
