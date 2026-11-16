import numpy as np,json
from pathlib import Path
p=Path('work/shakira-2160');x=np.load(p/'new.npy');y=np.load(p/'old.npy');data=json.loads((p/'verified-alignment.json').read_text())
for name,r in data.items():
 for a in r['anchors']:
  i=round(a['old']*20);v=y[i:i+160];best=(-1,None)
  for shift in range(-1795,-1783):
   w=x[i+shift:i+shift+160];s=float((v*w).sum()/np.sqrt((v*v).sum()*(w*w).sum()))
   if s>best[0]:best=(s,shift/20)
  a['local_score'],a['local_delta']=round(best[0],4),best[1]
 print(name,round(min(a['local_score'] for a in r['anchors']),3),sorted(set(a['local_delta'] for a in r['anchors'])))
(p/'verified-alignment.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
