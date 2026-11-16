import numpy as np,json
from pathlib import Path
p=Path('work/shakira-2160');x=np.load(p/'new.npy');y=np.load(p/'old.npy');data=json.loads((p/'alignment.json').read_text())
for name,r in data.items():
 scores=[]
 for a in r['anchors']:
  i=round(a['old']*20);j=round((a['old']-89.45)*20);v=y[i:i+80];w=x[j:j+80];s=float((v*w).sum()/np.sqrt((v*v).sum()*(w*w).sum()));a['expected_score']=round(s,4);scores.append(s)
 print(name,'min',round(min(scores),3),'bad',[(a['old'],a['expected_score']) for a in r['anchors'] if a['expected_score']<.85])
(p/'verified-alignment.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
