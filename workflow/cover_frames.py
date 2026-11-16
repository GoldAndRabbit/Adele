"""Read both platforms' raw-frame references with absolute source timestamps."""
import hashlib
import re
from pathlib import Path

from workflow.live.paths import read_json, ROOT
from workflow.vertical_cover import original_source


def candidate_frames(concert, item):
    directory = concert.song_dir(item)
    info = read_json(directory / 'song.json', {})
    selection = read_json(concert.dir / 'vertical_source.json', {}).get('songs', {}).get(item['name'], {})
    span = selection.get('slice') or info.get('slice')
    begin = span[0] if span else 0
    try:
        source = original_source(concert, item)
        source_key = str(source.resolve())
    except FileNotFoundError:
        source = None
        source_key = str(info.get('source_file') or concert.source)
    rows = {}

    def add(at, origin, path=None, kind='cover', pool_frame=None):
        if pool_frame or (span and not span[0] <= at < span[1]):
            return
        milliseconds = round(at * 1000)
        identity = hashlib.sha256((source_key + ':' + str(milliseconds)).encode()).hexdigest()[:24]
        # Older JPEG names round source times to tenths of a second.
        # Merge only across origins inside that rounding error; retain both times.
        match = next((row for row in rows.values() if origin not in row['origins']
                      and abs(row['source_time_ms'] - milliseconds) <= 50), None)
        if match:
            identity = match['id']
        row = rows.setdefault(identity, dict(id=identity, t=milliseconds / 1000, kind=kind,
            origins=[], references=[], path=None, source=str(source) if source else None, source_time_ms=milliseconds,
            status='available' if source else 'source_offline', pool_frame=pool_frame))
        row['references'].append(dict(origin=origin, source_time_ms=milliseconds))
        if origin not in row['origins']:
            row['origins'].append(origin)
        if path and path.is_file():
            row['path'] = str(path)
            row['status'] = 'available'
            row['kind'] = kind

    folder = ROOT / 'work/fibo-batch' / concert.slug / 'selection' / item['name']
    marker = read_json(folder / 'source.json', {})
    if source and marker == dict(source=str(source), mtime=source.stat().st_mtime_ns, slice=span):
        for filename, at in read_json(folder / 'times.json', []):
            path = Path(filename)
            if path.parent == folder and path.is_file():
                add(at, '本曲原片', path)
    plan = read_json(concert.dir / 'fibo-cover-plan.json', {}).get(item['name'], {})
    active = read_json(directory / 'covers/ai/masters.json', [])
    if active and active[0].get('review_hash'):
        reviewed = active[0]
        plan = dict(reference=reviewed.get('original_reference') or reviewed['reference'],
                    source_time=reviewed['source_time'])
    if plan.get('reference') and plan.get('source_time') is not None:
        path = directory / 'covers/ai' / plan['reference']
        if path.is_file():
            add(plan['source_time'], 'AI 参考帧', path)
    for path in sorted((directory / 'covers').glob('frame_*.jpg')):
        match = re.fullmatch(r'frame_(?:(closeup|half|full|scene)_)?(\d+)_([\d.]+)s\.jpg', path.name)
        if match:
            add(float(match[3]), 'B站', path, match[1] or 'cover')
    for frame in read_json(directory / 'vertical/candidates.json', []):
        # Pool references already carry whole-source times; song rows store offsets.
        pool = frame.get('pool_frame')
        at = frame['time'] if pool else begin + frame['time']
        add(at, '抖音', concert.dir / 'cover_pool' / pool if pool else None, pool_frame=pool)
    return sorted(rows.values(), key=lambda row: row['t'])
