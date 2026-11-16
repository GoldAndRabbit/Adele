from pathlib import Path
from fractions import Fraction
import sys,os,re,json,shutil,time,subprocess
ROOT=Path('/Users/gold/repos/adele');sys.path[:0]=[str(ROOT),str(ROOT/'workflow'),str(ROOT/'work/external-concerts-followup')]
import run as base
base.ROOT=ROOT;base.BASE=ROOT/'work/coachella-lolla-previews';BASE=base.BASE
from workflow.live.paths import Concert,read_json,write_json,slugify
from workflow.lyrics_library import song_identity
from workflow.live.segment import norm
from workflow.browser_library import probe
base.load_env()

def checkpoint():
 while (BASE/'PAUSED').exists():time.sleep(10)
base.checkpoint=checkpoint

def item_for(job,idx,entry):
 return dict(idx=idx,name=f'{idx:02d}_{slugify(entry["title"])}',title=entry['title'],artist=job['artist'],artist_zh=job['artist_zh'],parts=entry['title'].split(' / '),kind='song',notes='',review_hidden=True)

def initialize(job):
 c=Concert(job['slug']);c.dir.mkdir(parents=True,exist_ok=True);(BASE/c.slug).mkdir(exist_ok=True)
 source=Path(job['source']);meta=read_json(BASE/c.slug/'source-probe.json') or probe(source);v=next(s for s in meta['streams'] if s['codec_type']=='video');a=next(s for s in meta['streams'] if s['codec_type']=='audio')
 info=dict(slug=c.slug,source_file=str(source),artist=job['artist'],artist_zh=job['artist_zh'],title=job['event'],title_zh=job['event'],title_en=job['event_en'],date=job['event'][:4],duration=float(meta['format']['duration']),width=v['width'],height=v['height'],fps_str=v['r_frame_rate'],fps=float(Fraction(v['r_frame_rate'])),video_codec=v['codec_name'],audio_codec=a['codec_name'],audio_channels=a['channels'],setlist_url=job['reference'])
 if c.slug=='chappell_lolla_brasil_2026':info.update(date='2026-03-21',audio_decoder='eac3_at',city='São Paulo',venue='Autódromo de Interlagos')
 if c.slug=='adele_one_night_only_2021':info.update(date='2021-10-24',broadcast_date='2021-11-14',city='Los Angeles',venue='Griffith Observatory')
 write_json(c.info,{**(c.load('info') or {}),**info})
 previous={x['name']:x for x in c.song_items()};items=[{**item_for(job,i,x),**previous.get(item_for(job,i,x)['name'],{})} for i,x in enumerate(job['catalog'],1)]
 write_json(c.setlist,{'source':job['reference'],'items':items})
 for it in items:
  d=c.make_song_dir(it)
  if not (d/'post_draft.json').exists():write_json(d/'post_draft.json',dict(song=dict(title=it['title'],artist=job['artist'],artist_zh=job['artist_zh']),performance=dict(event=job['event'],event_en=job['event_en'],date=info['date']),intro_text=f'{job["artist_zh"]}在{job["event"]}演唱《{it["title"]}》。',tags=[],sources=[job['reference']]))
 return c

def reusable_refs():
 out={};seen=set()
 for folder in (ROOT/'concerts').iterdir():
  if not folder.is_dir():continue
  c=Concert(folder.name)
  for it in c.song_items():
   artist=it.get('artist') or (c.load('info') or {}).get('artist','')
   if norm(artist) not in {'lady gaga','chappell roan','adele','heart'}:continue
   d=c.song_dir(it)
   if d.resolve() in seen or not (d/'lyrics.txt').is_file():continue
   seen.add(d.resolve());artist,title=song_identity(d)
   artist=artist or it.get('artist');title=title or it['title']
   origin=(d/'lyrics_source').read_text().strip() if (d/'lyrics_source').exists() else ''
   if artist and title and not origin.startswith('source-asr'):out.setdefault((norm(artist),norm(title)),d)
 return out

REFS={}
def reference(job,it,c):
 d=c.song_dir(it)
 if (d/'lyrics.txt').exists() and (d/'lyrics.txt').stat().st_size>10:return
 found=[];sources=[]
 for part in it['parts']:
  ref=REFS.get((norm(job['artist']),norm(part)))
  if ref and ref.resolve()!=d.resolve():found.append((ref/'lyrics.txt').read_text().strip());sources.append(str(ref/'lyrics.txt'))
 if len(found)==len(it['parts']):
  (d/'lyrics.txt').write_text('\n\n'.join(found)+'\n');(d/'lyrics_sections.txt').write_text((d/'lyrics.txt').read_text());(d/'lyrics_source').write_text('reused-local-reference');write_json(d/'lyrics_reference_reuse.json',dict(sources=sources))
  # Reuse an existing confirmed song title with the same artist and track.
  from workflow.song.title_translation import resolved,save
  if len(it['parts'])==1 and resolved(REFS[(norm(job['artist']),norm(it['title']))]):save(d,dict(title=it['title'],title_zh=resolved(REFS[(norm(job['artist']),norm(it['title']))]),artist_zh=job['artist_zh'],reason='复用同曲中文译名'))
 else:
  base.lyrics({**it,'artist':'Heart'} if it['title']=='Barracuda' else it,d)
  if (d/'lyrics_source').read_text().startswith('source-asr'):raise ValueError('参考歌词缺失，不能把粗识别当参考歌词')
 print('REFERENCE',c.slug,it['name'],flush=True)
