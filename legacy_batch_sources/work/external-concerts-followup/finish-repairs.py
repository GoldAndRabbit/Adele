"""Reconcile primary and repair results against deliverables once concurrent workers finish."""
import runpy
from repair import *

def wait_worker(pid):
    while True:
        try: os.kill(pid,0)
        except ProcessLookupError:return
        time.sleep(30)

def audit():
    runpy.run_path(str(BASE/'preview-audit.py'),run_name="__main__")
    return read_json(BASE/'preview-audit.json')

if __name__=="__main__":
    with (BASE/'finish-repairs.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for pid in map(int,sys.argv[1:]):wait_worker(pid)
        checkpoint()
        report=audit()
        for job in QUEUE:
            incomplete=[r for r in report['items'] if r['concert']==job['slug'] and not r['ready']]
            if not incomplete:continue
            # A source or API failure is distinct from a human editorial decision.
            # Only retry recoverable upstream errors; leave human edits intact.
            results=read_json(BASE/job['slug']/'results.json',[])
            reasons=[r.get('error','') for r in results if r['status']=='needs_repair']
            print('reconcile',job['slug'],len(incomplete),reasons,flush=True)
            repair(job)
        final=audit()
        stats={}
        for job in QUEUE:
            rows=[r for r in final['items'] if r['concert']==job['slug']]
            stats[job['slug']]=dict(catalog=len(rows),ready=sum(r['ready'] for r in rows),
                located=len(read_json(BASE/job['slug']/'locations.json',[])),
                outstanding=[r['title'] for r in rows if not r['ready']])
        write_json(BASE/'results.json',stats)
        write_json(BASE/'state.json',dict(status='pending_human_review' if final['ready']==final['total'] else 'needs_targeted_repair',ready=final['ready'],total=final['total'],results=stats))
