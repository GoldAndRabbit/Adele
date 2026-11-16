"""Resume per-song repair and dispatch; preserve active renderers and exact evidence."""
from pathlib import Path
import contextlib
import fcntl
import subprocess
import sys
import time
from datetime import datetime
import psutil
from workflow.live.paths import Concert,read_json,write_json
from workflow.source_lyrics import capture
from workflow.content_check import check
from posts.concert_delivery_20261116.release_observed_music import tick

BASE=Path(__file__).parent
RELOAD_TOKEN='Reload repair workers with full original transcript and source-clock checks.\n'
OWNED={'posts.concert_delivery_20261116.extend_remaining_music',
       'posts.concert_delivery_20261116.release_observed_music',
       'posts.concert_delivery_20261116.repair_captions_all',
       'posts.concert_delivery_20261116.review_remaining_music'}

def state(**values):
    current=read_json(BASE/'repair-status.json',{})
    current.update(values,updated_at=datetime.now().astimezone().isoformat())
    write_json(BASE/'repair-status.json',current)

def run(module,cycle):
    state(stage=module,cycle=cycle)
    with (BASE/f'repair-cycle-{cycle}.log').open('a') as log:
        result=subprocess.run([sys.executable,'-u','-m',module],stdout=log,stderr=subprocess.STDOUT)
    return result.returncode

if __name__=='__main__':
    with (BASE/'repair-batch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        (BASE/'repair-batch.pid').write_text(str(__import__('os').getpid()))
        # Existing API/preview repair tasks finish their current song. Production
        # workers are never terminated or included in this handoff.
        state(status='running',stage='waiting_for_previous_repair_song')
        while any(OWNED.intersection(p.info['cmdline'] or []) for p in psutil.process_iter(['cmdline'])):
            time.sleep(2)
        pause=BASE/'REPAIR_PAUSED'
        if pause.exists():
            if pause.read_text()!=RELOAD_TOKEN:raise SystemExit('Repair pause changed externally')
            pause.unlink()
        for cycle in range(1,4):
            if (BASE/'REPAIR_PAUSED').exists():break
            queue=read_json(BASE/'queue.json')
            if not queue['blocked_jobs']:break
            state(cycle=cycle,stage='refresh_original_clock_and_saved_vocals')
            with (BASE/f'repair-cycle-{cycle}.log').open('a') as log,contextlib.redirect_stdout(log):
                for slug in queue['concerts']:
                    try:
                        c=Concert(slug);items=[c.item(k.split('/')[1]) for k in queue['blocked_jobs'] if k.startswith(slug+'/')]
                        if items:capture(c,items=items,workers=5)
                        for it in items:
                            try:check(c,it)
                            except Exception as error:print('曲目检查异常',slug,it['name'],str(error),flush=True)
                    except Exception as error:print('原片检查异常，继续其他场次',slug,str(error),flush=True)
            run('posts.concert_delivery_20261116.review_remaining_music',cycle)
            tick()
            run('posts.concert_delivery_20261116.repair_captions_all',cycle)
            tick()
            run('posts.concert_delivery_20261116.extend_remaining_music',cycle)
            tick()
        blocked=read_json(BASE/'queue.json')['blocked_jobs']
        state(status='needs_attention' if blocked else 'repairs_complete_production_continues',
              stage='remaining_findings' if blocked else 'dispatching',remaining=list(blocked))
        print('Repair pass finished; remaining',len(blocked),flush=True)
