"""CBS-only source, English audio, independent song ASR, browser previews and shared pool."""
import sys,subprocess,shutil,traceback
from pathlib import Path
from types import SimpleNamespace
from workflow.live.paths import *
from workflow.browser_library import prepare_browser,probe
from workflow.live.setlist import parse
from workflow.live.lyrics import stage_lyrics
from workflow.live.package import draft_meta
from workflow.vertical_post import posting_inputs,submission
BASE=ROOT/'work/dua-cbs';SLUG='an_evening_with_dua_lipa_cbs_2024';c=Concert(SLUG)
assert (ROOT/'work/shakira-2160/complete.json').exists(),'先完成夏奇拉'
source=Path('/Volumes/harddisk_5T/thunder_downloads/An Evening With Dua Lipa (CBS cut) HDTV MPEG2 1080i DD5.1-ilya2129.ts/An Evening With Dua Lipa (CBS cut) HDTV MPEG2 1080i DD5.1-ilya2129.ts')
external=Path('/Volumes/harddisk_5T/adele-workflow/sources/concerts')/SLUG;external.mkdir(parents=True,exist_ok=True)
c.dir.mkdir(exist_ok=True);c.logs.mkdir(exist_ok=True);c.songs.mkdir(exist_ok=True)
real=Path('/Volumes/harddisk_5T/adele-workflow/posts')/SLUG;real.mkdir(parents=True,exist_ok=True)
if not (POSTS/SLUG).exists():(POSTS/SLUG).symlink_to(real,target_is_directory=True)
def run(cmd):subprocess.run([str(x) for x in cmd],check=True)
master=external/'source-english.mkv'
if not master.exists():
 pending=external/'source-english.partial.mkv';run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y','-i',source,'-map','0:v:0','-map','0:2','-c','copy','-avoid_negative_ts','make_zero',pending]);pending.replace(master)
info={'slug':SLUG,'source_file':str(master),'original_source_file':str(source),'source_audio_stream':2,'artist':'Dua Lipa','artist_zh':'杜阿·利帕','title':'An Evening with Dua Lipa · CBS cut','title_zh':'2024年杜阿·利帕皇家阿尔伯特音乐厅演唱会','title_en_short':'An Evening with Dua Lipa','date':'2024-10-17','broadcast_date':'2024-12-15','city':'London','venue':'Royal Albert Hall','broadcast':'CBS cut','douyin_event_short':'2024伦敦现场','width':1920,'height':1080,'fps':30000/1001,'fps_str':'30000/1001','field_order':'tt','video_codec':'mpeg2video','audio_codec':'ac3','audio_rate':48000,'audio_channels':6,'duration':float(probe(master)['format']['duration']),'has_captions':True,'metadata_sources':['https://www.itv.com/presscentre/presscentre/presscentre/media-releases/evening-dua-lipa-air-itv-later-year','https://www.paramountpressexpress.com/cbs-entertainment/releases/?view=110486-cbs-presents-an-evening-with-dua-lipa-a-new-primetime-concert-special-airing-sunday-dec-15']}
write_json(c.info,info)
if not c.source.exists():c.source.symlink_to(master)
tracks=[('Houdini',10,308),('Levitating',468,729),('Maria',765,994),('Training Season',994,1210),('These Walls',1437,1650),('Love Again',1722,2020),('Illusion',2233,2460),('Cold Heart',2640,2948),('Be the One',2990,3278),('Dance the Night',3404,3650),("Don't Start Now",3650,3918)]
text='\n'.join(t+(' | Dua Lipa & Elton John | CBS cut; with Elton John' if t=='Cold Heart' else ' | Dua Lipa | CBS cut') for t,a,b in tracks)+'\n';c.setlist_txt.write_text(text)
items=parse(text,'Dua Lipa');write_json(c.setlist,{'source':'CBS source closed captions; performance order verified','items':items})
write_json(c.dir/'vertical_preview.json',{'cover_artist_en':{it['name']:it['artist'] for it in items},'cover_artist_zh':{it['name']:('杜阿·利帕 & 埃尔顿·约翰' if it['title']=='Cold Heart' else '杜阿·利帕') for it in items}})
segments={'items':[dict(idx=it['idx'],name=it['name'],title=it['title'],kind='song',start=a,end=b,manual=True,review='pending',evidence='CBS embedded captions; includes musical intro/outro') for it,(_,a,b) in zip(items,tracks)]};write_json(c.segments,segments)
import pysubs2
cc=pysubs2.load(str(BASE/'captions.srt'));cc.shift(s=-.412411);cc.save(str(c.captions))
# Reuse only reference lyrics, never another performance's timed subtitles.
old=Concert('dualipa_mexico2025');olditems={it['title'].casefold():it for it in old.song_items()}
for it,(_,a,b) in zip(items,tracks):
 d=c.make_song_dir(it);(d/'logs').mkdir(exist_ok=True);(d/'reports').mkdir(exist_ok=True)
 if not (d/'song.json').exists():
  ref=olditems.get(it['title'].casefold());meta={}
  if ref:
   source_dir=old.song_dir(ref);meta=read_json(source_dir/'song.json',{})
   for filename in ['lyrics.txt','lyrics_sections.txt']:
    if (source_dir/filename).exists():shutil.copy2(source_dir/filename,d/filename)
  meta={k:v for k,v in meta.items() if k in ['genius','genius_urls','lang','langs']};meta.update(it);meta.update(slice=[a,b],preview=[a,b]);write_json(d/'song.json',meta)
# Fetch missing reference lyrics through the established workflow.
sys.path.insert(0,str(ROOT/'workflow'));stage_lyrics(c,SimpleNamespace(force=False,songs=None))
for it in items:
 name=it['name'];d=c.song_dir(it);status=BASE/(name+'.json')
 if read_json(status,{}).get('status')=='ready':continue
 try:
  write_json(status,{'status':'preparing'});print('PREPARING',name,flush=True)
  clip=prepare_browser(c,it)
  if not (d/'audio.flac').exists():run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-i',clip,'-vn','-ac','2','-ar','48000','-c:a','flac',d/'audio.flac'])
  if not (d/'vocals.wav').exists():run([SEP_PY,ROOT/'workflow/separate_roformer.py',d/'audio.flac','-o',d/'vocals.wav'])
  write_json(status,{'status':'refining'})
  if not (d/'subs/lyrics_poetic.ass').exists():
   with (d/'logs/cbs-refine.log').open('w') as log:subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',SLUG,name],stdout=log,stderr=subprocess.STDOUT,check=True)
  seg=next(r for r in segments['items'] if r['name']==name);draft_meta(c,it,seg,SimpleNamespace(force=False))
  draft,event,zh=posting_inputs(c,it,read_json(d/'post_draft.json'));write_json(d/'vertical/douyin_submission.json',submission(draft,event,zh));write_json(d/'vertical/candidates.json',read_json(d/'vertical/candidates.json',[]) if (d/'vertical/selected.json').exists() else [])
  write_json(status,{'status':'ready','file':str(clip)});print('READY',name,flush=True)
 except Exception:
  write_json(status,{'status':'failed','error':traceback.format_exc()});print(traceback.format_exc(),flush=True)
from workflow.cover_pool_quality import upgrade
(c.dir/'cover_pool').mkdir(exist_ok=True);count=upgrade(c,target=100)
fail=[it['name'] for it in items if read_json(BASE/(it['name']+'.json'),{}).get('status')!='ready']
write_json(BASE/'result.json',{'songs':len(items),'failed':fail,'approved_candidates':count})
print('CBS_FINISHED',len(items),fail,count,flush=True)
