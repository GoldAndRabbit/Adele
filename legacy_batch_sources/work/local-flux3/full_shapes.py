from mflux.models.flux3.flux3_initializer import Flux3Initializer
from mflux.models.common.config import ModelConfig
from mlx.utils import tree_flatten
import pathlib,json
from types import SimpleNamespace
m=SimpleNamespace(model_config=ModelConfig.flux3_image_klein());Flux3Initializer._init_models(m)
for key in ('vae','text_encoder','transformer'):
 orig=pathlib.Path('/Volumes/harddisk_5T/adele-workflow/work/flux3/models/klein-mlx-4bit')/key
 header={}
 for p in orig.glob('*.safetensors'):
  with p.open('rb') as f:header.update(json.loads(f.read(int.from_bytes(f.read(8),'little'))))
 target=dict(tree_flatten(getattr(m,key).parameters()))
 print(key,'missing',list(sorted(target.keys()-header.keys()))[:15])
 print('unexpected',list(sorted(k for k in header.keys()-target.keys() if not k.endswith(('biases','scales'))))[:20])
 print('shapes',[(k,v.shape,header[k]['shape']) for k,v in target.items() if k in header and list(v.shape)!=header[k]['shape']][:50])
