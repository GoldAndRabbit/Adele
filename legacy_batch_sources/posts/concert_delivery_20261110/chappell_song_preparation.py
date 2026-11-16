from pathlib import Path
import fcntl,sys,subprocess,traceback
sys.path.insert(0,str(Path('work/coachella-lolla-previews').resolve()))
import common
from workflow.subtitle_metadata_batch import ensure_audio, subtitle_audit
slug='chappell_lolla_brasil_2026'
c=common.Concert(slug)
folder=common.BASE/slug
with (folder/'preparation.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    locations={x['idx']:x for x in common.read_json(folder/'locations.json')}
    for item in c.song_items():
        d=c.song_dir(item)
        hit=locations.get(item['idx'])
        if not hit or not (d/'lyrics.txt').is_file():
            continue
        try:
            song=common.read_json(d/'song.json',{})
            song.setdefault('slice',[hit['start'],hit['end']])
            common.write_json(d/'song.json',{**item,**song,'source_file':c.load('info')['source_file'],'lang':song.get('lang','en')})
            if subtitle_audit(c,item)['status']=='missing':
                print('准备字幕',item['name'],flush=True)
                ensure_audio(c,item)
                with (folder/(item['name']+'-subtitles.log')).open('a') as log:
                    subprocess.run([sys.executable,'-u','-m','workflow.song.run','song',slug,item['name']],check=True,stdout=log,stderr=subprocess.STDOUT)
        except Exception:
            traceback.print_exc()
