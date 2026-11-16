"""Prepare the secondary GPU queue ahead of primary ASR/translation work."""
from pathlib import Path
import sys,fcntl,traceback
sys.path[:0]=[str(Path(__file__).resolve().parent),'/Users/gold/repos/adele']
from remote_audio import ensure_audio
from workflow.live.paths import Concert,read_json,write_json
base=Path(__file__).resolve().parent
with (base/'audio-prefetch.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for slug in ['gaga_coachella_2025','chappell_lolla_brasil_2026']:
  c=Concert(slug);hits={r['idx']:r for r in read_json(Path('work/coachella-lolla-previews')/slug/'locations.json',[])}
  for it in reversed(c.song_items()):
   if (base/'PAUSED').exists():break
   # The current coordinator already owns Gaga 01; never duplicate it.
   if slug=='gaga_coachella_2025' and it['idx']==1:continue
   d=c.song_dir(it)
   if (d/'vocals.wav').is_file() or it['idx'] not in hits:continue
   try:
    info=read_json(d/'song.json',{});info.setdefault('slice',[hits[it['idx']]['start'],hits[it['idx']]['end']]);info['source_file']=c.load('info')['source_file'];write_json(d/'song.json',info)
    print('PREFETCH',slug,it['name'],flush=True);ensure_audio(c,it,prepare_preview=False)
   except Exception as exc:print('PREFETCH_FAILED',slug,it['name'],str(exc),flush=True)
