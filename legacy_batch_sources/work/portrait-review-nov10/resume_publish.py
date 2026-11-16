from workflow.reviewed_cover import stage,publish,verify_release,digest
from workflow.live.paths import Concert,read_json,write_json
from pathlib import Path
import sys
base=Path(__file__).resolve().parent
for arg in sys.argv[1:]:
 i,x=arg.split('=');x=float(x);f=base/i;req=f/('final.json' if (f/'final.json').is_file() else 'reviewed.json');q=read_json(req);q['framing'].update(focus=[x,.33],portrait_focus=[x,.33]);write_json(req,q);s=f/'release-final';token=stage(req,s);publish(s,token);receipt=verify_release(s,q['slug'],'http://127.0.0.1:8160')
 c=Concert(q['slug']);d=c.song_dir(c.item(q['name']));m=read_json(d/'covers/ai/masters.json')[0]
 target=c.dir/'fibo-cover-plan.json';plan=read_json(target);spec=plan[q['name']];spec.update(source_time=q['source_time'],scene_note=q['scene_note'],reference=m['original_reference'],original_reference=m['original_reference'],review_framing=q['framing'],portrait_crop_x=x,reference_lock=dict(reference_sha256=m['source_frame_hash'],source_time=q['source_time'],reason='竖版主唱居中，已按本曲原片复核'))
 if spec.get('group_review') or spec.get('solo_review'):
  spec['solo_review']=dict(performer={16:'Macklemore',17:'Rihanna',35:'P!nk',44:'Eminem'}.get(int(i),c.item(q['name'])['artist']),front_clear=True,reason='指定主唱面部在母图和竖裁中可辨认',reference_sha256=m['source_frame_hash'])
 write_json(target,plan);print(i,receipt['master'],flush=True)
