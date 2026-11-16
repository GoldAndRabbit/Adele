from pathlib import Path
import json,subprocess,datetime
ROOT=Path('/Users/gold/repos/adele');B=ROOT/'posts/eminem_batch_20261030'
m=json.loads((B/'manifest.json').read_text());report=[]
for j in m['singles']:
 out=ROOT/'posts'/j['name']/'post/cover'
 if not list(out.glob('frame_*.jpg')):
  print(j['name'],'no frames yet; queue will use corrected layout',flush=True);continue
 desired={'version':2,'artist_zh':'埃米纳姆','event':j.get('cover_event',''),'sub_fit':'natural'}
 stamp=out/'layout.json'
 if stamp.exists() and json.loads(stamp.read_text())==desired:continue
 args=[str(ROOT/'.venv/bin/python'),str(ROOT/'workflow/make_cover.py'),'--name',j['name'],'--title',' / '.join(j['parts']),
       '--subtitle','Eminem · 中英字幕','--artist-zh','埃米纳姆','--sub-fit','natural','--recompose']
 if j.get('cover_event'):args+=['--event',j['cover_event']]
 with (B/(j['name']+'_cover_layout_fix.log')).open('a') as log:
  result=subprocess.run(args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 if result.returncode:raise RuntimeError(j['name']+' recompose failed')
 stamp.write_text(json.dumps(desired,ensure_ascii=False,indent=2)+'\n')
 report.append({'name':j['name'],'pairs':len(list(out.glob('frame_*.jpg'))),'layout':desired})
 print(j['name'],'updated',report[-1]['pairs'],'cover pairs',flush=True)
(B/'cover_layout_fix_report.json').write_text(json.dumps({'at':datetime.datetime.now().isoformat(),'jobs':report},ensure_ascii=False,indent=2)+'\n')
