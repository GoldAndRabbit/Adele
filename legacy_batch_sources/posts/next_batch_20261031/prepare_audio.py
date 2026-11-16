from pathlib import Path
import subprocess,json,os,fcntl,time
R=Path('/Users/gold/repos/adele');B=Path(__file__).parent;P=R/'.venv/bin/python'
lock=(B/'audio.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
s={'pid':os.getpid(),'status':'running','jobs':{}}
def save(n,stage,**kw):
 s['current']=n;s['jobs'][n]={'stage':stage,**kw};s['at']=time.time();(B/'audio_status.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
for j in json.loads((B/'manifest.json').read_text())['jobs']:
 n=j['name'];d=R/'posts'/n
 try:
  with (B/'logs'/f'{n}_audio_prepare.log').open('a') as log:
   if not (d/'audio.flac').exists():
    save(n,'extract_audio');subprocess.run(['ffmpeg','-v','error','-y','-i',str(d/'source.mp4'),'-vn','-c:a','flac','-ar','48000','-sample_fmt','s32',str(d/'audio.flac')],stdout=log,stderr=log,check=True)
   save(n,'separate');subprocess.run([str(P),'workflow/make_mv.py','--name',n,'--from','separate','--to','separate'],cwd=R,stdout=log,stderr=log,check=True)
  save(n,'audio_ready')
 except Exception as e:save(n,'blocked',reason=str(e))
s['current']=None;s['status']='finished';(B/'audio_status.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
