exec(open('work/grammy-ts-review/qwen.py').read().split('with ThreadPoolExecutor')[0])
exec(open('work/grammy-ts-review/extract.py').read().split('def extract')[0].split('bounds=')[0] if False else '')
from importlib.util import spec_from_file_location,module_from_spec
s=spec_from_file_location('extract','work/grammy-ts-review/extract.py');e=module_from_spec(s);s.loader.exec_module(e)
tasks=[]
for name,(a,b) in e.bounds.items():
 for i,t in enumerate(np.arange(a,b,45)):tasks.append((name+'-'+str(i),float(t),min(45,b-t)))
with ThreadPoolExecutor(max_workers=3) as ex:list(ex.map(job,tasks))
