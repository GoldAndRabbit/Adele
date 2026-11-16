"""Audit missing catalog entries against source ASR; save evidence, never guess cuts."""
import sys,json
from pathlib import Path
sys.path[:0]=['/Users/gold/repos/adele','/Users/gold/repos/adele/workflow']
from workflow.live.paths import read_json,write_json,Concert
from llm import chat_json
base=Path(__file__).resolve().parent
for slug,indices in [('adele_one_night_only_2021',[4]),('gaga_coachella_2025',[3,9,10,12])]:
 c=Concert(slug);rows=read_json(Path('work/coachella-lolla-previews')/slug/'transcript.json');catalog=[{'idx':i['idx'],'title':i['title']} for i in c.song_items() if i['idx'] in indices]
 result=chat_json('只根据给出的实际原片ASR核查是否演唱了指定歌曲，不能根据歌单猜测。每项输出idx、found、first、last（必须是实际ASR行t）、anchor（原ASR中的连续词）、reason。仅谈论提到曲名而没有演唱不得认定。无证据返回found=false。输出JSON {items:[]}。',json.dumps({'catalog':catalog,'source_asr':rows},ensure_ascii=False),label='剩余曲目证据核查 '+slug)
 write_json(base/('remaining-location-'+slug+'.json'),result);print('LOCATION_AUDIT_SAVED',slug,flush=True)
