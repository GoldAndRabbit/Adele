"""Use the second Mac for GPU separation; keep ASR and posting on the primary."""
import subprocess,shlex,hashlib,fcntl
from pathlib import Path
from contextlib import contextmanager
from workflow.live.paths import ROOT
from workflow.preview_batch import enable_browser
SSH=['ssh','-i',str(Path.home()/'.ssh/adele_render_worker'),'-oBatchMode=yes','-oConnectTimeout=10','zhaojing@192.168.3.10']
REMOTE='Library/Caches/adele/subtitle-worker'
@contextmanager
def dispatcher_slot():
 with (ROOT/'work/three-concert-subtitles-20261114/remote-separation-dispatch.lock').open('a') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX)
  yield

def cmd(code):
 return subprocess.run([*SSH,code],check=True)

def sync(src,dest):
 subprocess.run(['rsync','-a','--partial','-e',shlex.join(SSH[:-1]),str(src),str(dest)],check=True)

def _ensure_audio(c,it,prepare_preview=True):
 d=c.song_dir(it)
 if prepare_preview:enable_browser(c,it)
 audio=d/'audio.flac'
 if not audio.is_file():
  pending=d/'audio.pending.flac'
  source=d/'vertical/original-selected.mp4'
  seek=[]
  decoder=[]
  if not prepare_preview:
   from workflow.live.paths import read_json
   info=read_json(d/'song.json');source=Path(info['source_file']);a,b=info['slice'];seek=['-ss',str(a),'-t',str(b-a)]
   audio_decoder=c.load('info',{}).get('audio_decoder')
   decoder=['-c:a',audio_decoder] if audio_decoder else []
  subprocess.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y',*decoder,'-i',str(source),*seek,'-map','0:a:0','-vn','-ac','2','-ar','48000','-c:a','flac',str(pending)],check=True)
  pending.replace(audio)
 if (d/'vocals.wav').is_file():return
 with dispatcher_slot():
  if (d/'vocals.wav').is_file():return
  name=c.slug+'--'+it['name'];job=REMOTE+'/jobs/'+name
  cmd('mkdir -p '+shlex.quote(job))
  sync(audio,'zhaojing@192.168.3.10:'+job+'/audio.flac')
  log=ROOT/'work/three-concert-subtitles-20261114'/('remote--'+name+'.log')
  with log.open('a') as out:
   subprocess.run([*SSH,'export PATH=/opt/homebrew/bin:$PATH; '+REMOTE+'/venv/bin/python '+REMOTE+'/workflow/separate_roformer.py '+shlex.quote(job+'/audio.flac')+' -o '+shlex.quote(job+'/vocals.wav')],check=True,stdout=out,stderr=subprocess.STDOUT)
  tmp=d/'vocals.remote.pending.wav';sync('zhaojing@192.168.3.10:'+job+'/vocals.wav',tmp)
  import soundfile as sf
  a=sf.info(str(audio));v=sf.info(str(tmp))
  if abs(a.duration-v.duration)>.3:raise ValueError('Remote vocals duration mismatch')
  tmp.replace(d/'vocals.wav')
  print('REMOTE_AUDIO_READY',name,flush=True)

def ensure_audio(c,it,prepare_preview=True):
 with (c.song_dir(it)/'audio-preparation.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  return _ensure_audio(c,it,prepare_preview)
