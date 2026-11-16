"""Only prepare source review players; never render/publish portraits."""
import json,subprocess,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from workflow.live.paths import Concert,read_json,write_json
c=Concert('grammys_2014'); policy=read_json(c.dir/'vertical_source.json'); sync=read_json('work/grammy-ts60/sync.json')
diffs=read_json(c.dir/'source_differences.json')['songs']
root=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014')

def convert(src,out,start=0,end=None,sequential=False,deint=False):
 if out.is_file():return
 out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_name('pending-'+out.name)
 cmd=['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y']
 if start and not sequential:cmd+=['-ss',str(start)]
 cmd+=['-i',str(src)]
 if start and sequential:cmd+=['-ss',str(start)]
 if end is not None:cmd+=['-t',str(end-start)]
 cmd+=['-map','0:v:0','-map','0:a:0']
 if deint:cmd+=['-vf','bwdif=mode=send_field:parity=tff:deint=all','-r','50']
 cmd+=['-c:v','h264_videotoolbox','-b:v','14M','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-movflags','+faststart',str(tmp)]
 subprocess.run(cmd,check=True);tmp.replace(out)

def link(src,d,name):
 dst=d/'vertical'/name;dst.parent.mkdir(exist_ok=True)
 if not dst.exists():dst.symlink_to(src)

def task(n):
 d=c.song_dir(c.item(n)); folder=root/'source-comparisons'/n;folder.mkdir(parents=True,exist_ok=True)
 meta={}; a,b=policy['songs'][n]['slice'];clean=Path(policy['songs'][n]['directory'])/'source.mp4'
 if n in diffs:
  link(clean,d,'original-ts.mp4');meta['ts']={'start':0}
  old=read_json(Path('work/grammy-ts-review/original-metadata')/n/'song.json'); x,y=old['slice']
  oldpath=folder/'old720.mp4';convert(c.source,oldpath,x,y)
  link(oldpath,d,'original-720.mp4');meta['old']={'start':0}
 else:
  native=root/'ts60-songs'/n/'song50.mkv';lead=sync[n]['lead']
  if n=='02_royals':native=root/'ts60-royals/song50.mkv';lead=0
  out=folder/'ts.mp4'
  if native.is_file():convert(native,out)
  elif clean.is_file():convert(clean,out);lead=0
  else:convert(policy['source'],out,a,b,sequential=True,deint=True);lead=0
  link(out,d,'original-ts.mp4');meta['ts']={'start':lead}
 write_json(d/'vertical/originals.json',meta);print('READY',n,flush=True)

if __name__=='__main__':
 names=list(diffs)+[n for n in policy['songs'] if n not in diffs]
 with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(task,names))
