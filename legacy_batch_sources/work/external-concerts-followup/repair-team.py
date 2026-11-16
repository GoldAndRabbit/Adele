from run import *
import shutil
from datetime import datetime
load_env()
c=Concert("lorde_iheart_2017");it=c.item("05_team");d=c.song_dir(it)
record=read_json(d/'song.json');old=record['slice']
assert old==[1120,1320] and not (d/'zh_fixed.json').exists()
folder=BASE/c.slug
backup=DATA/"work/external-concert-preview"/c.slug/("team-before-cut-"+datetime.now().strftime("%Y%m%d-%H%M%S"));backup.mkdir(parents=True)
for name in ("song.json","subs","audio.flac","vocals.wav","delivery_bundle.json"):
    p=d/name
    if p.exists():p.rename(backup/name)
for name in ("segments.json","setlist.json","vertical_source.json"):
    shutil.copy2(c.dir/name,backup/name)
spans=read_json(folder/'locations.json')
next(r for r in spans if r['idx']==5)['start']=980
write_json(folder/'locations.json',spans)
policy=read_json(c.dir/'vertical_source.json');policy['songs'][it['name']]['slice']=[980,1320];write_json(c.dir/'vertical_source.json',policy)
record.update(slice=[980,1320]);write_json(d/'song.json',record)
items=c.load('setlist');next(r for r in items['items'] if r['name']==it['name'])['review_hidden']=True;write_json(c.setlist,items)
result=produce(next(j for j in QUEUE if j['slug']==c.slug))
write_json(folder/'repair-summary.json',result)
print(result,flush=True)
