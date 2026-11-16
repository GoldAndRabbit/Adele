from pathlib import Path
import sys,os,json,subprocess,fcntl,requests,hashlib,shutil
R=Path('/Users/gold/repos/adele');sys.path[:0]=[str(R),str(R/'workflow')];os.chdir(R)
from workflow.live.lyrics import fetch_part
from workflow.llm import load_env
from workflow.song.title_translation import display_title
from rapidfuzz.fuzz import ratio
P=R/'.venv/bin/python';B=Path(__file__).parent
lock=(B/'queue_jn2kgdpozz4.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);load_env()
current=json.loads((R/'posts/upload_batch_20261031/status.json').read_text())
assert '--prepare-now' in sys.argv or all((Path(x['directory'])/'post/publish.json').exists() for x in current['items']),'Current upload batch incomplete'
m=json.loads((B/'manifest.json').read_text());state=json.loads((B/'status_jn2kgdpozz4.json').read_text()) if (B/'status_jn2kgdpozz4.json').exists() else {'jobs':{}};state.update(pid=os.getpid(),status='running')
(B/'logs').mkdir(exist_ok=True)
def save(n,stage,**kw):
 state['current']=n;state['jobs'][n]={'stage':stage,**kw};(B/'status_jn2kgdpozz4.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');print(n,stage,kw,flush=True)
def cmd(n,stage,args):
 save(n,stage)
 with (B/'logs'/f'{n}_{stage}.log').open('a') as f:subprocess.run(list(map(str,args)),cwd=R,stdout=f,stderr=subprocess.STDOUT,check=True)
for j in m['jobs']:
 if '--only' in sys.argv and j['name'] != sys.argv[sys.argv.index('--only')+1]:continue
 n=j['name'];d=R/'posts'/n;d.mkdir(exist_ok=True) # heavy preparation stays on the internal disk
 cookies=['--cookies-from-browser','chrome'] if j['platform']=='youtube' else []
 try:
  if (d/'subs/lyrics_poetic.ass').exists() and (R/'concerts/singles/songs'/n/'preview.mp4').exists():save(n,'review_ready');continue
  cmd(n,'download',[P,R/'posts/additional_batch_20261030/download.py','--name',n,'--url',j['url'],'--from','download','--to','download',*cookies])
  if not (d/'post'/f'{n}.json').exists():cmd(n,'preliminary_metadata',[P,'workflow/make_meta.py','--name',n,'--subtitle-langs','英语,中文','--note','仅使用源视频标题和简介中的事实识别歌曲、歌手、场次；缺少依据的年份和场次不要猜。'])
  post=json.loads((d/'post'/f'{n}.json').read_text());song=post['song'];title=song['title'];artist=song['artist'];assert title and artist,'Source song identity missing'
  if not (d/'lyrics.txt').exists():
   save(n,'reference_lyrics');plain=sections=None;source={}
   with requests.Session() as sess:
    sess.headers['User-Agent']='Mozilla/5.0'
    try:
     u,plain,sections,_=fetch_part(sess,title,artist);source={'provider':'Genius','url':u}
    except Exception as ex:
     res=sess.get('https://lrclib.net/api/search',params={'q':artist+' '+title},timeout=30);res.raise_for_status()
     matches=[x for x in res.json() if x.get('plainLyrics') and ratio(x.get('trackName','').casefold(),title.casefold())>=85 and ratio(x.get('artistName','').casefold(),artist.casefold())>=75]
     texts={x['plainLyrics'].strip() for x in matches}
     assert len(texts)==1,'Genius unavailable and alternative references are missing or ambiguous: '+str(ex)
     pick=matches[0];plain=pick['plainLyrics'];sections=plain;source={'provider':'LRCLIB','url':'https://lrclib.net/api/get/'+str(pick['id']),'genius_error':str(ex)}
   (d/'lyrics.txt').write_text(plain+'\n');(d/'lyrics_sections.txt').write_text(sections+'\n');(d/'reference_source.json').write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n')
  if not (d/'vocals.wav').exists():cmd(n,'separate',[P,'workflow/make_mv.py','--name',n,'--url',j['url'],'--from','prep','--to','separate',*cookies])
  cmd(n,'precision_subtitles',[P,'-u','-m','workflow.song.run','post',n])
  assert all((d/p).exists() for p in ['subs/lines.json','subs/profile.json','subs/translation/result.json','subs/lyrics_poetic.ass','title_translation.json'])
  cmd(n,'post_description',[P,'workflow/make_meta.py','--name',n,'--reintro','--note','仅写视频来源可支持的事实；歌词介绍依据已取得的参考歌词；未知演出信息不猜测。'])
  post=json.loads((d/'post'/f'{n}.json').read_text());prefs=json.loads((d/'presentation_preferences.json').read_text()) if (d/'presentation_preferences.json').exists() else {};post['tags']=prefs.get('tags',post.get('tags',[]));post['title']=post.get('title','').replace('贾斯汀·汀布莱克','贾老板').replace('贾斯汀·提姆布莱克','贾老板') if prefs.get('artist_zh')=='贾老板' else post.get('title','');s=post['song'];s['artist_zh']=prefs.get('artist_zh',s.get('artist_zh') or s['artist']);(d/'post'/f'{n}.json').write_text(json.dumps(post,ensure_ascii=False,indent=2)+'\n');perf=post.get('performance') or {};event=perf.get('event_zh') or perf.get('event') or '现场版'
  if any(x in event.casefold() for x in ['official','music video','音乐录影带','mv']):event='MV'
  cmd(n,'covers',[P,'workflow/make_cover.py','--name',n,'--title',prefs.get('cover_title',display_title(s['title'])),'--subtitle',prefs.get('cover_subtitle',s['artist']+' · 中英字幕'),'--artist-zh',s.get('artist_zh') or s['artist'],'--event',event,'--sub-fit','natural'])
  cmd(n,'watermark',[P,'-m','workflow.song.watermark','post',n]);cmd(n,'review',[P,'-m','workflow.live.singles',n]);save(n,'review_ready')
 except Exception as ex:save(n,'blocked',reason=str(ex))
state['current']=None;state['status']='finished';(B/'status_jn2kgdpozz4.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
