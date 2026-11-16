from pathlib import Path
import pysubs2,shutil
from workflow.live.paths import read_json,write_json
from workflow.browser_library import probe
base=Path('work/coachella-lolla-previews');folder=Path('/Volumes/harddisk_5T/thunder_downloads/Adele One Night Only (2021) [1080p] [WEBRip] [5.1] [YTS.MX]');source=next(folder.glob('*.mp4'))
job=dict(slug='adele_one_night_only_2021',source=str(source),bytes=source.stat().st_size,event='2021年阿黛尔一夜限定演唱会',event_en='Adele One Night Only',artist='Adele',artist_zh='阿黛尔',reference='https://en.wikipedia.org/wiki/Adele_One_Night_Only',catalog=[dict(title=t,artist='Adele',artist_zh='阿黛尔') for t in 'Hello|Easy on Me|Skyfall|I Drink Wine|Someone Like You|When We Were Young|Make You Feel My Love|Hold On|Rolling in the Deep|Love Is a Game'.split('|')])
jobs=read_json(base/'jobs.json');jobs=[j for j in jobs if j['slug']!=job['slug']]+[job];write_json(base/'jobs.json',jobs)
d=base/job['slug'];d.mkdir(exist_ok=True);m=probe(source);write_json(d/'source-probe.json',m)
captions=next(folder.glob('*.srt'));shutil.copy2(captions,d/'captions.srt')
subs=pysubs2.load(str(captions));duration=float(m['format']['duration'])
rows=[dict(t=t,end=min(t+20,duration),text=' '.join(e.plaintext.replace('\n',' ') for e in subs if t*1000<=e.start<(t+20)*1000 and 'YTS.MX' not in e.plaintext)) for t in range(0,int(duration),20)]
write_json(d/'transcript.json',rows)
print('Adele registered, source captions',len(subs))
