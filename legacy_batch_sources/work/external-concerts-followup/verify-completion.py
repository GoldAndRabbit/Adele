from run import *
import runpy,urllib.request
from datetime import datetime
ns=runpy.run_path(str(BASE/'preview-audit.py'))
previous=read_json(BASE/'live-audit.json')
new=[r for r in previous['items'] if not r['ready']]
rows=[];counts={}
for j in QUEUE+[dict(slug=s,catalog=Concert(s).song_items()) for s in ('grammys_2025','grammys_2026')]:
    group=ns['audit_job'](j['slug'],j['catalog']);rows+=group
    counts[j['slug']]=dict(catalog=len(group),ready=sum(r['ready'] for r in group),outstanding=[r['title'] for r in group if not r['ready']])
for row in new:
    slug=row['concert'];name=row['link'].split('/')[-1]
    url=f'http://127.0.0.1:8160/api/concerts/{slug}/songs/{name}'
    x=json.load(urllib.request.urlopen(url,timeout=60))
    if not (x['subtitles_ready'] and x['browser_portrait'] and x['douyin_submission'] and x['preview']):
        raise RuntimeError(f'审核页未就绪 {slug}/{name}')
    req=urllib.request.Request('http://127.0.0.1:8160'+x['preview'],headers={'Range':'bytes=0-31'})
    with urllib.request.urlopen(req,timeout=30) as stream:
        if b'ftyp' not in stream.read(32):raise RuntimeError(f'视频响应异常 {name}')
print(counts,flush=True)
if not all(r['ready'] for r in rows):sys.exit(1)
stamp=datetime.now().isoformat()
subset=[r for r in rows if r['concert'] not in ('grammys_2025','grammys_2026')]
for dest in ('live-audit.json','preview-audit.json'):
    write_json(BASE/dest,dict(updated=stamp,total=len(subset),ready=len(subset),items=subset))
stats={j['slug']:dict(counts[j['slug']],located=len(read_json(BASE/j['slug']/'locations.json'))) for j in QUEUE}
write_json(BASE/'results.json',stats)
write_json(BASE/'state.json',dict(status='pending_human_review',ready=len(subset),total=len(subset),updated=stamp,results=stats))
write_json(BASE/'nine-show-audit.json',dict(updated=stamp,ready=len(rows),total=len(rows),human_approved=False,results=counts,items=rows))
