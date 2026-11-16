"""Continue the final sweep once both source-audio repairs have verified."""
import os
import sys
import time
from pathlib import Path

ROOT = Path('/Users/gold/repos/adele')
sys.path.insert(0, str(ROOT))
from post_bili.full_library import run
from post_bili.receipt import current_receipt
from workflow.live.paths import read_json

folder = ROOT / 'posts/bili_full_20261114'
repair_pid = int(sys.argv[1])
proofs = [folder / 'final-seven-repair' / (name + '-flac-verified.json')
          for name in ['02_royals', '04_dark_horse']]
while not all(p.exists() for p in proofs):
    try:
        os.kill(repair_pid, 0)
    except ProcessLookupError:
        raise SystemExit('音轨修复进程已结束，但核验未全部通过；保留成品待检查')
    time.sleep(5)

plan_path = folder / 'resume-plan.json'
plan = read_json(plan_path)


def count():
    return sum(bool(current_receipt(Path(s['path'])))
               for b in plan['batches'] for s in b['songs'])


def pending_markers():
    return {str(Path(s['path']) / 'post/bili_batch_pending')
            for b in plan['batches'] for s in b['songs']
            if (Path(s['path']) / 'post/bili_batch_pending').exists()}


for attempt in range(3):
    before = count()
    pending_before = pending_markers()
    print('音轨核验通过，继续最终补投轮次', attempt + 1, flush=True)
    # Shares the main uploader lock: existing uploads finish before this sweep.
    run(plan_path)
    after = count()
    verified = read_json(folder / 'collections_verified.json', {})
    if after == sum(len(b['songs']) for b in plan['batches']) and all(
            b['slug'] in verified for b in plan['batches']):
        print('全部当前成品已提交，全部合集已有核验凭证', flush=True)
        break
    if after <= before and pending_markers() == pending_before:
        print('本轮没有新增回执，保留异常给下一次检查', flush=True)
        break
