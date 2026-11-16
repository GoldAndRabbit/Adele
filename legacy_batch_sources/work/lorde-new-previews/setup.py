from pathlib import Path
import shutil,sys,os
root=Path.cwd()
exec((root/'work/lorde-new-previews/concert.py').read_text().split('print(r.produce')[0])
c=r.Concert(job['slug']);folder=r.BASE/c.slug
bak=folder/'initial-localization';bak.mkdir(exist_ok=True)
for key in ('01_hammer','02_what_was_that'):
 p=r.POSTS/c.slug/key
 if p.exists() and not (bak/key).exists():p.rename(bak/key)
for f in ['vertical_source.json','results.json']:
 path=(c.dir if f.startswith('vertical') else folder)/f
 if path.exists() and not (bak/f).exists():path.rename(bak/f)
starts=[0,213,445,718,916,1206,1449,1572,1740,1970,2157,2379,2632]
ends=starts[1:]+[None];ends[4]=1123;ends[8]=1945
off=26.414;duration=float(r.probe(s)['format']['duration'])
labels=['铁锤','那是什么','变形者','年度人物','最受宠的女儿','时事','验孕棒','和我一起准备','碎玻璃','如果她能看见现在的我','大卫','肋骨','绿光']
spans=[]
for idx,(start,end,t,z) in enumerate(zip(starts,ends,titles,labels),1):
 a=round(start+off,3);b=duration if end is None else round(end+off,3)
 spans.append(dict(idx=idx,start=a,end=b,artist_zh='洛德'))
 key=f'{idx:02d}_{r.slugify(t)}';d=c.make_song_dir(dict(name=key))
 from workflow.song.title_translation import save,resolved
 from workflow.lyrics_library import genius_lookup
 for other in (root/'concerts').glob('lorde_*/songs/*_'+r.slugify(t)):
  if other.resolve()!=d.resolve() and resolved(other):z=resolved(other);break
 save(d,dict(title=t,title_zh=z,artist_zh='洛德',reason='同曲译名或本场审阅稿'))
 r.write_json(d/'post_draft.json',dict(song=dict(title=t,title_zh=z,artist='Lorde',artist_zh='洛德'),performance=dict(event=job['event'],event_en=job['event_en'],date='2025-06-27'),intro_text=f'2025年6月27日，洛德在格拉斯顿伯里音乐节 Woodsies 舞台演唱《{t}》。',tags=[]))
r.write_json(folder/'locations.json',spans)
print(r.produce(job),flush=True)
