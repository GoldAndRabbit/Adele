from pathlib import Path
import json,subprocess,sqlite3,sys,os,fcntl
B=Path(__file__).resolve().parent;R=B.parents[1];sys.path.insert(0,str(R))
from workflow.storage import archive_root
lock=(B/'shakira.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
dest=archive_root()/'sources/concerts/shakira_madrid_2026';dest.mkdir(parents=True,exist_ok=True)
t=json.loads(sqlite3.connect((Path.home()/'Library/Application Support/Thunder/etm3/etm_map.db').as_uri()+'?mode=ro',uri=True).execute('select create_param from etm_task where taskid=92').fetchone()[0]);h=t['info_hash'];assert h=='30728096FECD8269F1414F810B691112C16A3A60'
def state(stage,**data):(B/'shakira_state.json').write_text(json.dumps(dict(stage=stage,**data)))
state('retrieving_original_torrent',info_hash=h)
try:
 subprocess.run(['aria2c','--dir='+str(dest),'--seed-time=0','--enable-dht=true','--bt-save-metadata=true','--bt-metadata-only=false','--summary-interval=60','--auto-file-renaming=false','--allow-overwrite=false','magnet:?xt=urn:btih:'+h],check=True)
 f=next(dest.rglob(t['file_name']));assert f.is_file()
 v=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(f)]))
 assert abs(float(v['format']['duration'])-7492.241)<2 and {'audio','video'}<={s['codec_type'] for s in v['streams']}
 src=R/'concerts/shakira_madrid_2026/source.mp4';assert not src.exists() and not src.is_symlink() and dest.is_relative_to(archive_root())
 src.symlink_to(f);state('restored',file=str(f),probe=v)
except Exception as e:state('needs_retry',reason=str(e));raise
