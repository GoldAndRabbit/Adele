from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse,fcntl,json,subprocess,time,traceback
from contextlib import redirect_stdout
from workflow.storage import archive_root
from workflow.live.paths import Concert,read_json,write_json
from workflow.vertical_workflow import prepare, candidates
from workflow.vertical_preview import render
from workflow.portrait_validation import preview_problem
from workflow.vertical_cover import original_source, header_labels
from workflow.song.watermark import run_post
from PIL import Image

path=Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--queue-file", type=Path, default=path / "queue.json")
parser.add_argument("--concert", help="只处理指定场次")
parser.add_argument("--wait-for-slot", action="store_true", help="等当前竖屏队列结束后再取得锁")
args = parser.parse_args()
status = path / "status"
status.mkdir(exist_ok=True)
lock = (path / "queue.lock").open("a")
fcntl.flock(lock, fcntl.LOCK_EX if args.wait_for_slot else fcntl.LOCK_EX | fcntl.LOCK_NB)
if (path / "PAUSED").exists():
    raise SystemExit("竖屏制作已暂停")
rows = read_json(args.queue_file)
if args.concert:
    rows = [r for r in rows if r["concert"] == args.concert]
    if not rows:
        raise SystemExit(f"队列中没有场次 {args.concert}")
dest = archive_root() / "vertical-reviews"

def run(row):
    if (path/'PAUSED').exists(): return
    c=Concert(row['concert']);it=c.item(row['name']);d=c.song_dir(it);folder=d/'vertical'
    key=row['concert']+'--'+row['name'];report=status/(key+'.json')
    old=read_json(report,{})
    labels=header_labels(c,it)
    repair=read_json(path/'header-repairs.json',{}).get(key)
    pool_ok = not c.has_cover_pool or (old.get('cover_source')=='pool' and all(r.get('pool_frame') for r in read_json(folder/'candidates.json',[])))
    if old.get('status')=='ready' and pool_ok and (folder/'full.mp4').is_file() and (old.get('header')==labels or (not repair and 'header' not in old)) and not preview_problem(c,it,folder/'full.mp4'): return
    t=time.monotonic()
    def report_state(state,**extra):
        write_json(report,dict(status=state,title=row['title'],elapsed=round(time.monotonic()-t,1),**extra))
    report_state('running')
    try:
        original_source(c,it)
        if not folder.exists() and not folder.is_symlink():
            external=dest/c.slug/it['name'];external.mkdir(parents=True,exist_ok=True);folder.symlink_to(external,target_is_directory=True)
        if c.slug=='singles' and not (d/'watermark.json').is_file():run_post(it['name'])
        if repair:
            if repair['preview'] or preview_problem(c,it,folder/'full.mp4'): render(c,it,force=True,full=True)
            if repair['covers']: candidates(c,it,keep_existing=True,redraw=True)
        else:
            prepare(c,it)
        streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(folder/'full.mp4')]))['streams']
        video=next(s for s in streams if s['codec_type']=='video')
        assert (video['width'],video['height'],video['avg_frame_rate'])==(1080,1920,'30/1')
        assert any(s['codec_type']=='audio' for s in streams)
        assert abs(float(video['duration'])-row['sec'])<0.15,(video['duration'],row['sec'])
        covers=read_json(folder/'candidates.json',[]);assert len({r['file'] for r in covers})==18
        for cover in covers:
            with Image.open(folder/cover['file']) as im:assert im.size==(1080,1920);im.verify()
        problem=preview_problem(c,it,folder/'full.mp4')
        if problem: raise ValueError(problem)
        report_state('ready',header=labels,cover_source='pool' if c.has_cover_pool else 'song');print('READY',key,flush=True)
    except Exception:
        report_state('failed',error=traceback.format_exc());print('FAILED',key,flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:
    for f in as_completed([pool.submit(run,r) for r in rows]):f.result()
