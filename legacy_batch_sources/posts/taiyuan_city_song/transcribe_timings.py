import json
from pathlib import Path
import mlx_whisper
root=Path('/Users/gold/.codex/visualizations/2026/11/04/01a1a53c-553d-7a60-bb22-c5e7c5f7f7da/angel-local/dist')
out=Path(__file__).parent
cache=Path.home()/'.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo/snapshots'
model='/Users/gold/.cache/whisper/mlx-large-v3'
for t in json.loads((root/'recordings.json').read_text()):
 if not t.get('generation',{}).get('lyrics'):continue
 uid=t['url'].split('/')[-1];p=out/(uid+'-asr.json')
 if p.exists():continue
 print('START',uid,flush=True)
 result=mlx_whisper.transcribe(str(root/t['src']),path_or_hf_repo=model,language='zh',word_timestamps=True,verbose=False,condition_on_previous_text=False)
 p.write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print('DONE',uid,len(result['segments']),flush=True)
