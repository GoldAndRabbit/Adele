from workflow.live.paths import *
from pathlib import Path
import subprocess,json
c=Concert('an_audience_with_adele_2021');info=c.load('info');source=Path(info['source_file']);segments={x['name']:x for x in c.load('segments')['items']}
policy={'source':str(source),'songs':{}};names=[]
for it in c.song_items():
 d=c.song_dir(it);s=read_json(d/'song.json');seg=segments[it['name']];a,b=s['slice'];assert [a,b]==[seg['start'],seg['end']]
 assert a<=seg['lyric_start']<seg['lyric_end']<b
 folder=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews')/c.slug/'browser-sources'/it['name'];folder.mkdir(parents=True,exist_ok=True)
 out=folder/'source.mp4';expected={'source':str(source),'mtime':source.stat().st_mtime_ns,'slice':[a,b]}
 if not out.exists() or read_json(folder/'source.json')!=expected:
  tmp=folder/'source.pending.mp4'
  subprocess.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-y','-v','error','-ss',str(a),'-i',str(source),'-t',str(b-a),'-map','0:v:0','-map','0:a:0','-c:v','h264_videotoolbox','-b:v','12M','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-movflags','+faststart',str(tmp)],check=True)
  tmp.replace(out);write_json(folder/'source.json',expected)
 probe=json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_format','-show_streams','-of','json',str(out)]));assert abs(float(probe['format']['duration'])-(b-a))<.2
 for link in [d/'preview.mp4',d/'vertical/original-selected.mp4']:
  link.parent.mkdir(exist_ok=True);pending=link.with_name(link.name+'.pending');pending.unlink(missing_ok=True);pending.symlink_to(out);pending.replace(link)
 policy['songs'][it['name']]={'source':str(source),'kind':'original','slice':[a,b],'directory':str(folder)}
 s.update(preview_mode='browser',preview=[a,b],source_file=str(source),source_kind='original',source_review='pending');write_json(d/'song.json',s)
 names.append(it['name']);write_json(c.dir/'vertical_source.json',policy);write_json(c.dir/'browser_previews.json',{'songs':names})
 print('SOURCE_READY',it['name'],round(b-a,2),flush=True)
