"""Resume only unverified cover edits, respecting temporary request throttles."""
import os
import sys
import time
from pathlib import Path

ROOT = Path('/Users/gold/repos/adele')
sys.path.insert(0, str(ROOT))
from post_bili.edit_cover import sync
from post_bili.edit_description import redacted_error
from workflow.live.paths import read_json, write_json

folder = ROOT / 'posts/bili_super_bowl_20261115'
(folder / 'cover-worker.pid').write_text(str(os.getpid()))
for attempt in range(3):
    records = read_json(folder / 'prepared.json')
    state = read_json(folder / 'online-cover-updates.json', {})
    pending = [r for r in records if state.get(str(r['year']),{}).get('status') != 'verified']
    if not pending:
        break
    for index, row in enumerate(pending):
        try:
            state[str(row['year'])] = sync(row['path'], folder / 'online-before')
            print(row['year'], '两版封面已回读核验', flush=True)
        except (Exception, SystemExit) as error:
            reason = redacted_error(error)
            state[str(row['year'])] = {'status': 'needs_retry', 'error': reason}
            print(row['year'], '暂缓', reason, flush=True)
            if '412' in reason or '-702' in reason:
                write_json(folder / 'online-cover-updates.json', state)
                print('接口暂时拒绝请求，停止本轮并等待后重试', flush=True)
                break
        write_json(folder / 'online-cover-updates.json', state)
        if index + 1 < len(pending):
            time.sleep(15)
    if all(state.get(str(r['year']),{}).get('status') == 'verified' for r in records):
        break
    if attempt < 2:
        time.sleep(90)
print('线上封面结果', {k:v['status'] for k,v in state.items()}, flush=True)
