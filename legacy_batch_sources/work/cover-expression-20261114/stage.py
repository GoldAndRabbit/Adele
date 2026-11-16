from workflow.reviewed_cover import *
from workflow.live.paths import ROOT
b=ROOT/'work/cover-expression-20261114'
for n,focus in [('adele_send_my_love_mv_fk4bbf7b29w',[.5,.27]),('adele_rolling_in_deep_mv_ryeda3jcqqw',[.5,.29])]:
 d=b/n;s=read_json(d/'selection.json');p=d/'request.json';write_json(p,dict(slug='singles',name=n,mode='oil',run=str((d/'run1').resolve()),source_time=s['source_time'],raw=s['raw'],framing=dict(focus=focus,portrait_focus=focus,zoom=1)));print(n,stage(p,d/'stage'),flush=True)
