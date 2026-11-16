"""Observe remaining source boundaries, recording uncertainty without global stops."""
from pathlib import Path
import fcntl
import traceback
from concurrent.futures import ThreadPoolExecutor
from workflow.live.paths import read_json,write_json
from workflow.live.paths import Concert
from workflow.content_check import boundary_identity,digest
from posts.concert_delivery_20261116.repair_music_review import observe

BASE=Path(__file__).parent

def one(key):
    slug,name=key.split('/')
    try:
        for edge in ['start','end']:observe(slug,name,edge)
        c=Concert(slug)
        return key,{'status':'observed','observation_version':4,
                    'boundary_fingerprint':digest(boundary_identity(c,c.item(name)))}
    except Exception as error:
        traceback.print_exc();return key,{'status':'error','error':str(error)}

if __name__=='__main__':
    with (BASE/'music-repair.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        queue=read_json(BASE/'queue.json');status=read_json(BASE/'music-repair-status.json',{})
        jobs=[]
        for key in queue['blocked_jobs']:
            slug,name=key.split('/');c=Concert(slug)
            current=digest(boundary_identity(c,c.item(name)))
            previous=status.get(key,{})
            if (previous.get('status')!='observed' or previous.get('observation_version')!=4 or
                    previous.get('boundary_fingerprint')!=current):jobs.append(key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            for key,result in pool.map(one,jobs):
                status[key]=result;write_json(BASE/'music-repair-status.json',status)
