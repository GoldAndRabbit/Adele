from pathlib import Path
import json,subprocess,requests
from workflow.live.paths import Concert,read_json
jobs=read_json(Path(__file__).with_name('mexico-trims.json'))+[['grammys_2026','01_apt',0,4]]
for slug,key,old,cut in jobs:
 c=Concert(slug);d=c.song_dir(c.item(key))
 j=requests.get(f'http://127.0.0.1:8160/api/concerts/{slug}/songs/{key}',timeout=40).json()
 a,b=j['slice']
 assert a==round(old+cut,3) and j['preview_span']==[a,b],key
 measured=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(d/'preview.mp4')]))
 assert abs(measured-(b-a))<.25,key
 previous=read_json(d/'reports'/f'before_preview_trim_{old:g}_{cut}s'/'subs/lines.json')
 now=read_json(d/'subs/lines.json')
 expected=[(max(0,x['start_ms']-cut*1000),x.get('text')) for x in previous if x['end_ms']>cut*1000 and x['start_ms']<(cut+b-a)*1000]
 assert [(x['start_ms'],x.get('text')) for x in now]==expected,key
 print(key,round(measured,2),len(now),flush=True)
