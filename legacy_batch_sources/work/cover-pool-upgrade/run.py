from workflow.live.paths import *
from workflow.cover_pool_quality import upgrade
import traceback
slugs=['an_audience_with_adele_2021','dualipa_mexico2025','olivia_acl_lclxvyamuce','lorde_lolla_chile2026','eminem_detroit_anger_management','lorde_acl2026','shakira_madrid_2026']
for slug in slugs:
 try:
  n=upgrade(Concert(slug));write_json(ROOT/'work/cover-pool-upgrade'/f'{slug}.json',{'status':'ready','count':n});print('READY',slug,n,flush=True)
 except Exception:
  error=traceback.format_exc();write_json(ROOT/'work/cover-pool-upgrade'/f'{slug}.json',{'status':'failed','error':error});print('FAILED',slug,error,flush=True)
