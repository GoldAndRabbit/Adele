import traceback
from concurrent.futures import ThreadPoolExecutor,as_completed
from workflow.live.paths import Concert
from workflow.preview_batch import enable_browser
from urllib.request import urlopen
import json
c=Concert('singles')
groups=json.load(urlopen('http://127.0.0.1:8160/api/concerts'))
names={i['name'] for g in groups if g.get('kind') for i in g['tracks']}
with ThreadPoolExecutor(max_workers=2) as pool:
    jobs={pool.submit(enable_browser,c,it):it['name'] for it in c.song_items() if it['name'] in names}
    for job in as_completed(jobs):
        try:
            job.result()
            print('ready',jobs[job],flush=True)
        except Exception:
            traceback.print_exc()
            print('failed',jobs[job],flush=True)
