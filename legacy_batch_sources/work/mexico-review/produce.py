import traceback
from concurrent.futures import ThreadPoolExecutor,as_completed
from workflow.live.paths import Concert
from workflow.preview_batch import enable_browser
c=Concert('dualipa_mexico2025')
with ThreadPoolExecutor(max_workers=2) as pool:
    jobs={pool.submit(enable_browser,c,it):it['name'] for it in c.song_items()}
    for job in as_completed(jobs):
        try:
            job.result()
            print('ready',jobs[job],flush=True)
        except Exception:
            traceback.print_exc()
            print('failed',jobs[job],flush=True)
