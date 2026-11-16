from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from workflow.live.paths import read_json,write_json
from posts.concert_delivery_20261116.review_boundaries import one

BASE=Path(__file__).parent
priority=[('chappell_reading_2025','12_the_giver'),('chappell_lowlands_2025','10_picture_you'),
          ('chappell_lowlands_2025','16_pink_pony_club')]
jobs=[(row['concert'],row['song']) for row in read_json(BASE/'queue.json')['jobs'] if row['concert']!='singles']
jobs=priority+[row for row in jobs if row not in priority]
def run(row):
    try:
        result=one(*row)
        record={'status':result['status'],'issues':result['issues']}
    except Exception as exc:
        record={'status':'failed','error':str(exc)}
    dest=BASE/'content-progress'/row[0];dest.mkdir(parents=True,exist_ok=True)
    write_json(dest/(row[1]+'.json'),record)

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,jobs))
