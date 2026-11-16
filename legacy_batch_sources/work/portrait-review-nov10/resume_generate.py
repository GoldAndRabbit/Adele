from pathlib import Path
from workflow.live.paths import Concert,read_json,write_json
from PIL import Image
import sys,subprocess,time
root=Path(__file__).resolve().parent
for i,frame,box,note in [(16,'10',(.02,.03,.88,.94),'Macklemore in a black suit and white shirt with his arm extended against pale blue stage panels, eyes open in the same direction as the source'),(35,'eye79',(0,.14,.60,.86),'P!nk in front of a plain pale background, her eyes open, holding the silver microphone. Retain the full outline of her head inside the frame and leave the background empty')]:
 f=root/str(i);q=read_json(f/'reviewed.json'); c=Concert(q['slug']);a,b=read_json(c.dir/'vertical_source.json')['songs'][q['name']]['slice']
 raw=f/(frame+'.jpg');im=Image.open(raw);w,h=im.size;ref=f/'selected-clean.png';im.crop(tuple(round(v*k) for v,k in zip(box,(w,h,w,h)))).save(ref)
 run=f/'oil-selected';q.update(raw=str(raw),input=str(ref),run=str(run),source_time=a+(b-a)*(.07+.86*10/19 if i==16 else .035+.94*79/84),scene_note=note)
 write_json(f/'final.json',q)
 if not (run/'master.run.json').exists():
  if run.exists():run.rename(f/('interrupted-'+str(time.time_ns())))
  subprocess.run([sys.executable,'workflow/fibo_cover.py',str(ref),str(run),'--model','/Volumes/harddisk_5T/adele-workflow/work/flux3/models/fibo2-edit-turbo-bf16','--reference-width','768','--prompt','Paint this exact performance frame as a luminous oil painting. '+note+'. Preserve facial likeness and composition, no extra objects or people, no lettering.'],check=True)
