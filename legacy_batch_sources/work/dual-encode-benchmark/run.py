import json,os,subprocess as sp,sys,time,shutil
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from workflow.live.paths import Concert
from workflow import dual_render as render
BASE=Path('/Volumes/harddisk_5T/adele-workflow/products/benchmarks/drunk-parallel-20261106');BASE.mkdir(parents=True,exist_ok=True)
SOURCE=Path('/Volumes/harddisk_5T/adele-workflow/products/grammys_2014/01_drunk_in_love/apple-shared60-v1')
if len(sys.argv)>1:
 folder=Path(sys.argv[1]);kind=sys.argv[2];c=Concert('grammys_2014');render.configure(c,c.item('01_drunk_in_love'),folder);render.DURATION=30
 render.render(kind);sys.exit(0)
report={'source':str(SOURCE/'master60.mkv'),'sample':'首句前0.5秒起，共30秒；同一共享60fps母版','encoder':render.ENCODERS[render.DEFAULT_ENCODER],'rounds':[],'other_ffmpeg_processes':'existing paused (T state), 0% CPU; left untouched'}
for trial,mode in [(1,'serial'),(1,'parallel'),(2,'parallel'),(2,'serial')]:
 jobs=[]
 for kind in ['portrait','landscape']:
  d=BASE/f'round-{trial}-{mode}'/kind;d.mkdir(parents=True,exist_ok=True)
  for name in ['header.png','portrait-mask.png','landscape-mask.png','portrait.ass','landscape.ass']:
   shutil.copy2(SOURCE/name,d/name)
  if not (d/'master60.mkv').exists():(d/'master60.mkv').symlink_to(SOURCE/'master60.mkv')
  jobs.append((kind,d))
 start=time.monotonic();handles=[]
 for kind,d in jobs:
  log=(d/'worker.log').open('w');p=sp.Popen([sys.executable,__file__,str(d),kind],stdout=log,stderr=log);handles.append((kind,d,p,log))
  if mode=='serial':assert p.wait()==0,(kind,str(d))
 for kind,d,p,log in handles:assert p.wait()==0,(kind,str(d));log.close()
 elapsed=time.monotonic()-start
 row={'round':trial,'mode':mode,'wall_seconds':elapsed,'branches':[]}
 for kind,d in jobs:
  times=json.loads((d/'timings.json').read_text());row['branches'].append({'kind':kind,'seconds':times[-1]['seconds'],'directory':str(d)})
 report['rounds'].append(row);(BASE/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(row),flush=True)
# Decode validation is outside the timed measurement for all eight outputs.
for row in report['rounds']:
 for branch in row['branches']:
  d=Path(branch['directory']);file=d/('bilibili-4k60.mp4' if branch['kind']=='landscape' else 'douyin-1080p60.mp4')
  info=json.loads(sp.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-of','json',str(file)]));v=next(x for x in info['streams'] if x['codec_type']=='video')
  assert v['codec_name']=='hevc' and v['avg_frame_rate']=='60/1' and int(v['nb_frames'])==1800
  assert (v['width'],v['height'])==((3840,2160) if branch['kind']=='landscape' else (1080,1920))
  sp.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-xerror','-i',str(file),'-f','null','-'],check=True)
  branch['validation']={'codec':v['codec_name'],'frames':v['nb_frames'],'width':v['width'],'height':v['height'],'full_decode':'passed'}
report['averages']={mode:sum(r['wall_seconds'] for r in report['rounds'] if r['mode']==mode)/2 for mode in ['serial','parallel']}
report['saved_percent']=(1-report['averages']['parallel']/report['averages']['serial'])*100
(BASE/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('VALIDATED',json.dumps(report['averages']),report['saved_percent'],flush=True)
