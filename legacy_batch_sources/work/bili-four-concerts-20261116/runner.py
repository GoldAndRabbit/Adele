"""Resume just the four authorized concert batches until uploads and collections finish."""
import fcntl
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/Users/gold/repos/adele')
sys.path.insert(0, str(ROOT))
from post_bili.full_library import run
from post_bili.edit_description import redacted_error
from workflow.live.paths import read_json, write_json

FOLDER = ROOT / 'work/bili-four-concerts-20261116'
PLAN = FOLDER / 'plan.json'


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


with (FOLDER / 'runner.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sweep = 0
    while True:
        sweep += 1
        write_json(FOLDER / 'runner-status.json', dict(status='running', sweep=sweep, updated_at=now()))
        print('SWEEP', sweep, now(), flush=True)
        try:
            run(PLAN.resolve(), line='bda2')
        except (Exception, SystemExit) as error:
            print('SWEEP_ERROR', redacted_error(error), flush=True)
        state = read_json(FOLDER / 'progress.json', {'batches': {}})
        slugs = [batch['slug'] for batch in read_json(PLAN)['batches']]
        if all(state['batches'].get(slug, {}).get('status') == 'complete' for slug in slugs):
            write_json(FOLDER / 'runner-status.json', dict(status='complete', sweep=sweep, updated_at=now()))
            print('ALL_FOUR_CONCERTS_COMPLETE', now(), flush=True)
            break
        delay = min(300 * sweep, 1800)
        write_json(FOLDER / 'runner-status.json', dict(status='waiting_retry', sweep=sweep,
                   retry_after_seconds=delay, updated_at=now()))
        print('RETRY_SWEEP_IN', delay, flush=True)
        time.sleep(delay)
