from workflow.reviewed_cover import *
from workflow.live.paths import ROOT
b=ROOT/'work/cover-expression-20261114'
for n,candidates in [('adele_send_my_love_mv_fk4bbf7b29w',[(25.5,'close-25.5.jpg',.55,.24,1.55),(28,'close-28.0.jpg',.55,.24,1.55),(32.75,'close-32.75.jpg',.55,.24,1.55)]),('adele_rolling_in_deep_mv_ryeda3jcqqw',[(79.9,'last-79.9.jpg',.43,.27,1.1),(14.4,'last-14.4.jpg',.43,.3,1),(130,'mouth-130.0.jpg',.43,.3,1)])]:
 d=b/n;p=d/'shortlist-request.json';write_json(p,dict(slug='singles',name=n,candidates=[dict(source_time=t,frame=str((d/f).resolve()),framing=dict(focus=[x,y],portrait_focus=[x,y],zoom=z)) for t,f,x,y,z in candidates]));shortlist(p,d/'shortlist');print(n,flush=True)
