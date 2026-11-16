import sys,subprocess,os
from pathlib import Path
from workflow.live.paths import Concert,read_json,write_json
from workflow.live.singles import build
from workflow.preview_batch import enable_browser
from workflow.subtitle_metadata_batch import ensure_audio,prepare_metadata,subtitle_audit
from workflow.song.title_translation import save
from llm import load_env
load_env()
c=Concert('singles')
jobs=[('lorde_fallon_perfect_places_2017','Perfect Places','完美之地','吉米·法伦今夜秀','The Tonight Show Starring Jimmy Fallon'),('lorde_mmvas_2017','Green Light / Perfect Places','绿光 / 完美之地','iHeartRadio加拿大音乐录影带大奖','iHeartRadio Much Music Video Awards')]
for n,t,z,event,en in jobs:
 p=Path('posts')/n;p.mkdir(exist_ok=True)
 if n=='lorde_mmvas_2017' and not (p/'source.mp4').exists():(p/'source.mp4').symlink_to('/Volumes/harddisk_5T/adele-workflow/sources/posts/lorde_mmvas_2017/source.mp4')
 (p/'post').mkdir(exist_ok=True)
 ref=[Path('posts/perfect_places_mv/lyrics.txt')]
 if n=='lorde_mmvas_2017':ref.insert(0,Path('concerts/lorde_acl2026/songs/18_green_light/lyrics.txt'))
 (p/'lyrics.txt').write_text('\n\n'.join(f.read_text().strip() for f in ref)+'\n')
 info=dict(title=f'Lorde {t} 2017 {en}',song=dict(title=t,title_zh=z,artist='Lorde',artist_zh='洛德'),performance=dict(event='2017年'+event,event_en=en,date='2017'),intro={'performance':f'洛德在2017年{event}演唱《{t}》。'},tags=['Lorde',event])
 write_json(p/'post'/f'{n}.json',info);build([n]);it=c.item(n);d=c.song_dir(it)
 write_json(d/'post_draft.json',info);save(d,dict(title=t,title_zh=z,artist_zh='洛德',reason='复用已有同曲译名'))
 enable_browser(c,it);print(n,prepare_metadata(c,it),flush=True)
for n,*_ in jobs:
 it=c.item(n);d=c.song_dir(it)
 ensure_audio(c,it)
 for f in ("vocals.wav","audio.flac"):
  dst=Path("posts")/n/f
  if not dst.exists():dst.symlink_to((d/f).resolve())

 if not (d/'subs/lyrics_poetic.ass').exists():subprocess.run([sys.executable,'-u','-m','workflow.song.run','post',n],check=True)
 print(n,subtitle_audit(c,it),flush=True)
