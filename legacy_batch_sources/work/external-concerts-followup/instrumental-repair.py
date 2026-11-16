from run import *
import pysubs2
from workflow.preview_batch import enable_browser
from workflow.song.title_translation import save

c=Concert('grammys_2013');it=c.item('16_take_five');d=c.song_dir(it)
folder=BASE/c.slug
spans=read_json(folder/'locations.json')
record=next(s for s in spans if s['idx']==16)
record.update(start=6746,end=6825,artist_zh='斯坦利·克拉克 & 奇克·科里亚 & 肯尼·加勒特')
next(s for s in spans if s['idx']==17)['artist_zh']='扎克·布朗 & 布里塔妮·霍华德 & 埃尔顿·约翰 & 蒙福之子 & 梅维斯·斯台普斯 & T·本恩·伯内特'
write_json(folder/'locations.json',spans)
for i in [16,17]:
    item=next(t for t in c.song_items() if t['idx']==i);p=c.song_dir(item)/'post_draft.json'
    draft=read_json(p);draft['song']['artist_zh']=next(s for s in spans if s['idx']==i)['artist_zh'];write_json(p,draft)
s=read_json(d/'song.json');s.update(slice=[6746,6825],instrumental=True);write_json(d/'song.json',s)
save(d,{'title':'Take Five','title_zh':'休息五分钟','reason':'器乐演奏，曲名译注'})
(d/'lyrics.txt').write_text('[Instrumental]\n')
(d/'lyrics_source').write_text('instrumental verified against source frames and broadcast introduction')
out=d/'subs';out.mkdir(exist_ok=True)
ass=pysubs2.SSAFile()
ass.events.append(pysubs2.SSAEvent(start=0,end=5000,text=r'Take Five · Instrumental\N《休息五分钟》· 器乐演奏'))
ass.save(out/'lyrics_poetic.ass')
enable_browser(c,it)
sub=subtitle_audit(c,it);meta=prepare_metadata(c,it)
if sub['issues'] or meta['issues']:raise RuntimeError(str(sub['issues']+meta['issues']))
print('verified instrumental',d/'preview.mp4',flush=True)
