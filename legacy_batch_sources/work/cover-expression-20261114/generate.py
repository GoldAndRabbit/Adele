import os,json,time,resource,contextlib,sys
from pathlib import Path
from datetime import datetime
import mlx.core as mx
from mlx.utils import tree_flatten
from mflux.models.fibo2.cli.fibo2_edit_generate import Fibo2EditCommand,build_parser
from mflux.callbacks.callback_registry import CallbackRegistry
from mflux.callbacks.instances.memory_saver import MemorySaver
from PIL import Image,ImageOps,ImageDraw
base=Path('/Users/gold/repos/adele/work/cover-expression-20261114');jobs=json.loads((base/'batch-jobs.json').read_text());model=None
mx.set_cache_limit(1000**3)
for job in jobs:
 d=Path(job['run']);out=d/'master.png';started=datetime.now().astimezone().isoformat();start=time.monotonic()
 sys.argv=[sys.argv[0],'--model','/Volumes/harddisk_5T/adele-workflow/work/flux3/models/fibo2-edit-turbo-bf16','--base-model','fibo2-edit-turbo','--image-paths',str(d/'reference.png'),'--prompt',job['prompt'],'--width','1024','--height','576','--steps','4','--guidance','1','--seed','42','--metadata','--output',str(out)]
 args=build_parser().parse_args()
 with (d/'generate.log').open('w') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
  if model is None:
   model=Fibo2EditCommand.load(args)
   for name in ['vae','transformer','text_encoder']:
    weights=tree_flatten(getattr(model,name).parameters());print('Preloading',name,len(weights),flush=True)
    for j,(_,value) in enumerate(weights):
     mx.eval(value)
     if j%100==0: print('Loaded',name,j,flush=True)
  model.callbacks=CallbackRegistry();memory=MemorySaver(model,keep_text_encoder=True,keep_transformer=True,cache_limit_bytes=1000**3);model.callbacks.register(memory)
  image=Fibo2EditCommand.generate(model,args,42,job['prompt']);image.save(path=str(out),export_json_metadata=True)
  print(memory.memory_stats(),flush=True)
 meta=json.loads(out.with_suffix('.metadata.json').read_text());stats=dict(output=str(out),references=[str(d/'reference.png')],generation_seconds=meta['generation_time_seconds'],elapsed_seconds=round(time.monotonic()-start,3),peak_process_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,peak_mlx_gb=round(mx.get_peak_memory()/1e9,3),shared_batch_process=True)
 out.with_suffix('.run.json').write_text(json.dumps(stats,indent=2)+'\n');(d/'task-time.json').write_text(json.dumps(dict(started_at=started,finished_at=datetime.now().astimezone().isoformat(),shared_batch_process=True),indent=2)+'\n')
 ref=Image.open(d/'reference.png');art=Image.open(out);canvas=Image.new('RGB',(2048,576))
 for j,im in enumerate([ref,art]):canvas.paste(ImageOps.fit(im,(1024,576)),(j*1024,0))
 canvas.save(out.with_suffix('.comparison.jpg'),quality=94)
 print('GENERATED',job['name'],flush=True)
