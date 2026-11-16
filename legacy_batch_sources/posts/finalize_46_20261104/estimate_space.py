from pathlib import Path
import json,subprocess,shutil,os,time
from workflow.song.render import song_of,song_seconds
from workflow.live.paths import Concert
R=Path('/Users/gold/repos/adele')
def estimate(spec):
 d,span,_=song_of(spec);src=d/'source.mp4'
 if not src.exists():
  if not span:raise RuntimeError('缺少原视频')
  source=Concert(spec.split(':')[1]).source
  if ':grammys_2014:' in spec:
   local=Path('/Users/gold/Downloads/VA - The 56th Grammy Awards [2014] make/VA - The 56th Grammy Awards [2014].mkv')
   if local.is_file():source=local
  src.symlink_to(source)
 st=src.stat();seconds=song_seconds(d,span);cache=d/'space_estimate.json'
 signature=[str(src.resolve()),st.st_size,st.st_mtime_ns,seconds,list(span) if span else None]
 if cache.exists():
  saved=json.loads(cache.read_text())
  if saved.get('signature')==signature:return saved['required_bytes']
 info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=r_frame_rate','-of','json',str(src)],timeout=60));a,b=map(float,info['streams'][0]['r_frame_rate'].split('/'));fps=a/b
 folder=d/'space_samples';folder.mkdir(exist_ok=True);sizes=[]
 if fps<59.5:
  for i in range(16):
   t=(span[0] if span else 0)+seconds*(i+.5)/16;out=folder/f'{i:02}.jpg'
   subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(src),'-frames:v','1','-vf','scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1','-q:v','1',str(out)],check=True,timeout=45)
   sizes.append(out.stat().st_size)
 # JPEG q1 maximum observed frame * 1.75; full input+output coexist.
 # 8GiB untouched reserve plus intermediate and 7 MB/s final estimate.
 required=int((max(sizes)*1.75*(fps+60)*seconds if sizes else 0)+8*2**30+seconds*7e6+1*2**30)
 data={'signature':signature,'time':time.time(),'samples':sizes,'fps':fps,'seconds':seconds,'required_bytes':required,'free_bytes':shutil.disk_usage(d).free}
 tmp=cache.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));tmp.replace(cache);print(d.name,'space estimate GiB',required/2**30,flush=True);return required
