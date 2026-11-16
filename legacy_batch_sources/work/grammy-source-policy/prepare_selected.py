"""Prepare all selected full-song sources in one TS decode, never burn portrait previews."""
import subprocess,time,json
from pathlib import Path
from workflow.live.paths import Concert,read_json,write_json
from workflow.vertical_source import prepare
c=Concert('grammys_2014');p=read_json(c.dir/'vertical_source.json');todo=[]
def publish(n,row,out):
 d=c.song_dir(c.item(n));target=d/'vertical/original-selected.mp4';tmp=target.with_suffix('.pending');tmp.unlink(missing_ok=True);tmp.symlink_to(out.resolve());tmp.replace(target)
 if row['kind']=='ts':
  target=d/'preview.mp4';tmp=target.with_suffix('.pending');tmp.unlink(missing_ok=True);tmp.symlink_to(out.resolve());tmp.replace(target)
  info=read_json(d/'song.json');info['preview']=row['slice'];write_json(d/'song.json',info)
 print('READY',n,row['kind'],flush=True)
for n,row in p['songs'].items():
 directory=Path(row['directory']);directory.mkdir(parents=True,exist_ok=True);out=directory/'source.mp4'
 expected={'source':row['source'],'mtime':Path(row['source']).stat().st_mtime_ns,'slice':row['slice']}
 if out.is_file() and read_json(directory/'source.json')==expected:publish(n,row,out)
 elif row['kind']=='720p':publish(n,row,prepare(c,c.item(n)))
 else:todo.append((n,row,out,expected))
if todo:
 cmd=['/opt/homebrew/bin/ffmpeg','-nostdin','-v','warning','-y','-threads','4','-i',p['source']]
 for n,row,out,_ in todo:
  a,b=row['slice'];tmp=out.with_name('selected-pending.mp4')
  cmd+=['-ss',str(a),'-t',str(b-a),'-map','0:v:0','-map','0:a:0','-vf','bwdif=mode=send_field:parity=tff:deint=all','-r','50','-c:v','h264_videotoolbox','-b:v','14M','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-movflags','+faststart',str(tmp)]
 print('PREPARING',len(todo),'TS clips, one sequential source read',flush=True)
 subprocess.run(cmd,check=True)
 for n,row,out,expected in todo:
  tmp=out.with_name('selected-pending.mp4')
  probe=json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_entries','format=duration','-of','json',str(tmp)]))
  assert abs(float(probe['format']['duration'])-(row['slice'][1]-row['slice'][0]))<.15,n
  tmp.replace(out);write_json(out.parent/'source.json',expected);publish(n,row,out)
print('ALL READY',flush=True)
