from compare import *
from workflow.live.paths import Concert,write_json as wr,read_json as rd
from workflow.song.title_translation import save,sync
from workflow.preview_batch import metadata
import pysubs2
c=Concert('singles');title='天使（永远的北伦敦）';artist='路易斯·邓福德'
a=lines('the_angel_live')
for n,merges in [('the_angel_live',[(36,37),(83,84)]),('the_angel_gunnertv',[(95,96)])]:
 d=Path('posts')/n; display=c.song_dir(c.item(n));f=d/'post'/f'{n}.json';post=rd(f)
 post['song'].update(title_zh=title,artist_zh=artist)
 if n.endswith('gunnertv'):
  perf=dict(event='Arsenal Premier League Title Celebrations',event_en='Arsenal Premier League Title Celebrations',event_zh='阿森纳英超夺冠庆典',date='2026')
  post.update(performance=perf)
  post['intro']['song']=post['intro']['song'].split('2026年社区盾')[0]
  post['intro']['performance']='GunnerTV 发布的更新版以路易斯·邓福德的《天使（永远的北伦敦）》配合阿森纳 2025/26 赛季英超夺冠庆典画面。'
  post['tags']=['英超夺冠庆典' if '社区盾' in t else t for t in post['tags']]
  post['performance_sources']=['https://www.arsenal.com/news/10-incredible-moments-from-our-champions-parade-asnX77w3ecCv',post['source']['url']]
  sl=rd(c.setlist);next(i for i in sl['items'] if i['name']==n)['notes']=perf['event'];wr(c.setlist,sl)
 wr(f,post)
 rf=d/'subs/translation/result.json';R=rd(rf);lf=d/'subs/lines.json';L=rd(lf)
 for before,after in reversed(merges):
  prev,main=L[before],L[after];assert main['text']=='North London Forever!'
  u=next(u for u in R['units'] if u['start']==main['start_ms'] and u['orig']==main['text'])
  u['start']=main['start_ms']=min(main['start_ms'],prev['start_ms']);main['strategy']='副歌首词 North 延音，与后半句合并';main['qwen']=' '.join([prev['qwen'],main['qwen']]);u['heard']=main['qwen']
  if prev['text']:
   sp=next(v for v in R['units'] if v['orig']==prev['text'] and v['start']==prev['start_ms']);sp['dropped']='North 延音已并入副歌'
  del L[before]
 for u in R['units']:
  if u['type']=='歌词' and key(u['orig']) in a:u['v1']=a[key(u['orig'])]['v1']
 wr(rf,R);wr(lf,L)
 for path in [d,display]:save(path,dict(title=post['song']['title'],title_zh=title,artist_zh=artist,source='同曲已有定稿'))
 sync(d)
 draft=rd(display/'post_draft.json');draft.update(performance=post['performance'],intro=post['intro'],tags=post['tags']);wr(display/'post_draft.json',draft)
 metadata(c,c.item(n))
 srt_path=d/'subs/lyrics.srt';subs=pysubs2.load(srt_path);bad=[u for u in subs if u.plaintext.strip().lower()=='no nothing']
 for ev in bad:subs.events.remove(ev)
 for u in R['units']:
  if u['orig']=='North London Forever!':
   ev=next((v for v in subs if 'north london forever' in v.plaintext.lower() and abs(v.end-u['end'])<60),None)
   if ev:ev.start=u['start']
 subs.save(str(srt_path))
 print(n,rd(display/'post_draft.json')['song']['title_zh'])
