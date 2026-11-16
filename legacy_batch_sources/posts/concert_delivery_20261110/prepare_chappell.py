"""Resume only Chappell's preparation; other paused shows retain their own queue."""
import fcntl
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

root = Path.cwd()
sys.path.insert(0, str(root / 'work/coachella-lolla-previews'))
import common

slug = 'chappell_lolla_brasil_2026'
concert = common.Concert(slug)
folder = common.BASE / slug
job = next(j for j in common.read_json(common.BASE/'jobs.json') if j['slug'] == slug)
info = concert.load('info')
job = {**job, 'source': info['source_file']}
duration = info['duration']
lock = (folder/'preparation.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
# This process owns only the requested show; don't resume the shared three-show queue.
def checkpoint():
    if (folder/'PAUSED').exists():
        raise RuntimeError('Chappell preparation paused')
common.base.checkpoint = checkpoint

def references():
    common.REFS.update(common.reusable_refs())
    for item in concert.song_items():
        checkpoint()
        try:
            common.reference(job,item,concert)
        except Exception as exc:
            print('Reference pending',item['name'],type(exc).__name__,flush=True)

with ThreadPoolExecutor(max_workers=1) as pool:
    refs = pool.submit(references)
    pcm = folder/'mono16.pcm'
    if not pcm.exists():
        scratch = Path.home()/'Library/Caches/adele/chappell_mono16.pcm'
        scratch.parent.mkdir(exist_ok=True,parents=True)
        subprocess.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-y','-v','error','-c:a','eac3_at','-i',job['source'],'-map','0:a:0','-vn','-ar','16000','-ac','1','-af','aresample=async=1:first_pts=0','-f','s16le',str(scratch)],check=True)
        if abs(scratch.stat().st_size/32000-duration)>6:
            raise ValueError('Decoded audio duration mismatch')
        import shutil
        tmp=folder/'mono16.checked.partial'
        shutil.copyfile(scratch,tmp)
        tmp.replace(pcm)
        scratch.unlink()
    print('Audio ready', flush=True)
    rows=common.base.transcript(job,duration,folder)
    spans=common.base.locate(job,rows,folder)
    print('Located candidate spans',len(spans),'of',len(job['catalog']),flush=True)
    refs.result()
