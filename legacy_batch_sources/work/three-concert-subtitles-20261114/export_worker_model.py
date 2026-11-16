"""Prepare a standard MFLUX Q4 checkpoint once, without concurrent inference."""
from pathlib import Path
import fcntl,json,sys
import mlx.core as mx
from mlx.utils import tree_flatten
from mflux.models.fibo2.variants.edit.fibo2_edit import Fibo2Edit
from mflux.models.common.config.model_config import ModelConfig
base=Path('/Users/gold/repos/adele/work/three-concert-subtitles-20261114')
target=Path('/Users/gold/Library/Caches/adele/fibo2-edit-turbo-q4')
with (base/'fibo-remaining.lock').open('a') as drain, (Path.home()/'Library/Caches/adele/separator.lock').open('a') as slot:
 fcntl.flock(drain,fcntl.LOCK_EX);fcntl.flock(slot,fcntl.LOCK_EX)
 if (target/'READY.json').exists():sys.exit(0)
 mx.set_default_device(mx.cpu)
 print('EXPORT_START_CPU_Q4',flush=True)
 model=Fibo2Edit(model_config=ModelConfig.fibo2_edit_turbo(),quantize=4,model_path='/Volumes/harddisk_5T/adele-workflow/work/flux3/models/fibo2-edit-turbo-bf16')
 for name in ('vae','transformer','text_encoder'):
  for i,(_,value) in enumerate(tree_flatten(getattr(model,name).parameters())):
   mx.eval(value)
   if i%100==0:print('QUANTIZED',name,i,flush=True)
 model.save_model(str(target))
 (target/'READY.json').write_text(json.dumps({'model':'fibo2-edit-turbo','bits':4,'mflux':'0.24.0'}))
 print('EXPORT_DONE',target,flush=True)
