import os,subprocess as sp,sys
from pathlib import Path
from dotenv import dotenv_values
key=dotenv_values('/Users/gold/repos/Takit/workers/.dev.vars').get('ARK_API_KEY')
assert key,'Configured ARK_API_KEY missing'
env={**os.environ,'ARK_API_KEY':key,'PYTHONPATH':'.'}
for name in ['01_drunk_in_love','02_royals']:
 sp.run([sys.executable,'-m','workflow.dual_platform','grammys_2014',name,'--covers-only','--skip-failed-covers','--ai-cover-plan',f'concerts/grammys_2014/songs/{name}/covers/ai/seedream-plan.json'],env=env,check=True)
