from common import *
from concurrent.futures import ThreadPoolExecutor
jobs=read_json(BASE/'jobs.json')
rows=[]
for j in jobs:
 c=initialize(j)
 rows.extend((j,it,c) for it in c.song_items())
REFS.update(reusable_refs())
write_json(BASE/'reference-index.json',[dict(artist=k[0],title=k[1],directory=str(v)) for k,v in REFS.items()])
def one(row):
 job,it,c=row;checkpoint()
 try:reference(job,it,c);return dict(concert=c.slug,song=it['name'],status='reference_ready')
 except Exception as exc:
  print('REFERENCE_ERROR',c.slug,it['name'],str(exc),flush=True)
  return dict(concert=c.slug,song=it['name'],status='needs_reference',error=str(exc))
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(one,rows))
write_json(BASE/'reference-status.json',results)
