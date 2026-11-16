"""One local GPU job at a time while the peer handles one CPU job."""
from pathlib import Path
import fcntl,subprocess,sys
sys.path.insert(0,'/Users/gold/repos/adele')
from workflow.live.paths import Concert,ROOT,SEP_PY,read_json,write_json
base=Path(__file__).resolve().parent
with (base/'local-audio-queue.lock').open('a') as queue:
 fcntl.flock(queue,fcntl.LOCK_EX|fcntl.LOCK_NB)
 c=Concert('gaga_coachella_2025');hits={r['idx']:r for r in read_json(Path('work/coachella-lolla-previews')/c.slug/'locations.json',[])}
 for it in c.song_items():
  if (base/'PAUSED').exists():break
  if it['idx']<=2 or it['idx'] not in hits:continue
  d=c.song_dir(it)
  with (d/'audio-preparation.lock').open('a') as per_song:
   fcntl.flock(per_song,fcntl.LOCK_EX)
   if (d/'vocals.wav').is_file():continue
   print('LOCAL_GPU',it['name'],flush=True)
   try:
    info=read_json(d/'song.json',{});info.setdefault('slice',[hits[it['idx']]['start'],hits[it['idx']]['end']]);info['source_file']=c.load('info')['source_file'];write_json(d/'song.json',info)
    audio=d/'audio.flac'
    if not audio.is_file():
     a,b=info['slice'];tmp=d/'audio.local.pending.flac'
     subprocess.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y','-i',info['source_file'],'-ss',str(a),'-t',str(b-a),'-map','0:a:0','-vn','-ac','2','-ar','48000','-c:a','flac',str(tmp)],check=True);tmp.replace(audio)
    tmp=d/'vocals.local.pending.wav'
    subprocess.run([str(SEP_PY),str(ROOT/'workflow/separate_roformer.py'),str(audio),'-o',str(tmp)],check=True);tmp.replace(d/'vocals.wav');print('LOCAL_GPU_READY',it['name'],flush=True)
   except Exception as exc:print('LOCAL_AUDIO_FAILED',it['name'],str(exc),flush=True)
