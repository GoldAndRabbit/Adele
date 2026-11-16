import shutil,csv
from workflow.live.paths import *
import pysubs2
c=Concert('shakira_madrid_2026');base=ROOT/'work/shakira-2160';backup=base/'before'
if c.captions.exists():
 if not (backup/'captions.srt').exists():shutil.copy2(c.captions,backup/'captions.srt')
 es=pysubs2.load(str(backup/'captions.srt'));es.shift(s=-89.45);es.events=[e for e in es if e.end>0 and e.start<7290744]
 for e in es:e.start=max(0,e.start);e.end=min(7290744,e.end)
 es.save(str(c.captions))
for f in ['features.npz','title_ocr.json','captions_lines.json']:
 p=c.dir/f
 if p.exists() and not (backup/f).exists():shutil.move(str(p),str(backup/f))
rows=[]
for it in c.song_items():
 old=read_json(backup/it['name']/'song.json')['slice'];new=read_json(c.song_dir(it)/'song.json')['slice'];rows.append([it['title'],*old,*new,-89.45,'单曲相对字幕时间不变；待人工审核'])
with (base/'片源字幕对应.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f);w.writerow(['曲目','旧起点秒','旧终点秒','新起点秒','新终点秒','偏移秒','字幕处理']);w.writerows(rows)
print('timeline metadata synchronized',len(rows))
