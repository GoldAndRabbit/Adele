"""Capture actual original audio for this explicitly scoped production batch."""
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT=Path('/Users/gold/repos/adele')
sys.path.insert(0,str(ROOT))
from workflow.live.paths import Concert,write_json
from workflow.source_lyrics import capture

BASE=Path(__file__).parent
NAME='khalid_young_dumb_broke_mv_ipfjnp1gupc'

def one(slug):
    c=Concert(slug)
    items=[c.item(NAME)] if slug=='singles' else c.song_items()
    try:
        result=capture(c,items=items,workers=2)
        record={'status':'captured' if not any(r['failed'] for r in result) else 'failed','sources':result}
    except Exception as exc:
        record={'status':'failed','error':str(exc)}
    write_json(BASE/(slug+'-source-check.json'),record)
    print('SOURCE',slug,record,flush=True)

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(one,['singles','chappell_reading_2025','chappell_lowlands_2025']))
