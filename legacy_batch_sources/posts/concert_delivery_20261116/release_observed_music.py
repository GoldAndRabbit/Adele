"""Release individually passed songs; observe pending findings without head-of-line waits."""
from pathlib import Path
import fcntl
import time
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_check import selection
from workflow.music_review import apply
from posts.concert_delivery_20261116.repair_music_review import BASE as MUSIC_BASE

BASE=Path(__file__).parent

def tick():
    q=read_json(BASE/'queue.json');out={}
    for key in list(q['blocked_jobs']):
        slug,name=key.split('/');c=Concert(slug);it=c.item(name);span=selection(c,it)['slice']
        folder=MUSIC_BASE/slug/name;paths=[]
        for edge,cut in zip(['start','end'],span):
            found=[p for p in folder.glob(edge+'*.json') if read_json(p).get('planned_cut')==cut]
            if not found:break
            paths.append(found[-1])
        if len(paths)!=2:continue
        result=apply(c,it,*paths);out[key]={k:v for k,v in result.items() if k!='content'}
        if result.get('content',{}).get('status')=='passed':
            with (BASE/'config.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX);current=read_json(BASE/'queue.json')
                current['blocked_jobs'].pop(key,None);write_json(BASE/'queue.json',current)
            print('Released',key,flush=True)
    write_json(BASE/'music-adjudication.json',out)

if __name__=='__main__':
    with (BASE/'music-adjudication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Finite observation loop; it never spawns renderers or retries uploads.
        for _ in range(120):
            if (BASE/'REPAIR_PAUSED').exists():break
            tick()
            if not read_json(BASE/'queue.json').get('blocked_jobs'):break
            time.sleep(15)
