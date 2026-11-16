"""Register one completed local FIBO run and derive its four platform previews."""
import argparse
from datetime import datetime
import fcntl
import hashlib
from pathlib import Path
import shutil

from workflow.delivery_bundle import sync_cover_release
from workflow.ai_cover import render_variants, reviewed_revision
from workflow.live.paths import Concert, read_json, write_json


def register(concert, item, run, source_time):
    ai = concert.song_dir(item) / 'covers/ai'
    refs = ai / 'references'
    refs.mkdir(parents=True, exist_ok=True)
    master = run / 'master.png'
    meta = read_json(master.with_suffix('.metadata.json'))
    stats = read_json(master.with_suffix('.run.json'))
    reference = run / 'reference.png'
    ref_name = 'fibo-' + hashlib.sha256(reference.read_bytes()).hexdigest()[:16] + '.png'
    timing = read_json(run / 'task-time.json')
    if timing is None:
        stat = (run / 'generate.log').stat()
        timing = dict(finished_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                      started_at=datetime.fromtimestamp(stat.st_mtime - stats['elapsed_seconds']).astimezone().isoformat(),
                      timing_estimated=True)
    preprocess = read_json(run / 'preprocess.json', {})
    template = preprocess.get('prompt_template')
    label = 'FIBO 2.0 Edit Turbo · 油画' + (f' · {template}' if template else '')
    with (ai / '.fibo.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if reviewed_revision(ai):
            raise ValueError('已有复核封面，请在 reviewed_cover 中试排并提交新版本')
        if not (refs / ref_name).exists():
            shutil.copyfile(reference, refs / ref_name)
        variants = render_variants(concert, item, master, label, compact=True)
        row = dict(file=variants[0]['master'], label=label, provider='local', model=meta['model'],
                   runtime='MFLUX ' + meta['mflux_version'], precision=meta['precision'].split('.')[-1],
                   source_time=source_time, reference='references/' + ref_name,
                   prompt=meta['prompt'], prompt_template=template, scene_note=preprocess.get('scene_note'),
                   generation_seconds=stats['generation_seconds'],
                   elapsed_seconds=stats['elapsed_seconds'], peak_process_gb=round(stats['peak_process_bytes']/1e9, 2),
                   **timing)
        previous = read_json(ai / 'masters.json', [])
        write_json(ai / 'masters.json', [row] + [m for m in previous if m['file'] != row['file']])
    sync_cover_release(concert, item)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert')
    parser.add_argument('song')
    parser.add_argument('run', type=Path)
    parser.add_argument('--source-time', type=float, required=True, help='Source time in seconds')
    args = parser.parse_args()
    concert = Concert(args.concert)
    register(concert, concert.item(args.song), args.run, args.source_time)
