from pathlib import Path
import sys,os,json
from concurrent.futures import ThreadPoolExecutor
root=Path.cwd();sys.path[:0]=[str(root),str(root/'workflow'),str(root/'work/external-concerts-followup')]
import run as base
base.ROOT=root;base.BASE=root/'work/coachella-lolla-previews';base.load_env()
from workflow.live.paths import write_json
DATA=Path('/Volumes/harddisk_5T/thunder_downloads')
names=[('gaga_coachella_2025','Lady Gaga - Live at Coachella Festival 2025 [2160p].mkv','Lady Gaga','嘎嘎小姐','2025年科切拉音乐节','Coachella Valley Music and Arts Festival','https://www.setlist.fm/setlist/lady-gaga/2025/empire-polo-club-indio-ca-35e0d6f.html','Bloody Mary|Abracadabra|Judas|Scheiße|Garden of Eden|Poker Face|Perfect Celebrity|Disease|Paparazzi|Alejandro|The Beast|Killah|Zombieboy|Die With a Smile|How Bad Do U Want Me|Shadow of a Man / Kill for Love|Born This Way|Shallow|Vanish Into You|Bad Romance'),('chappell_lolla_brasil_2026','Lollapalooza.Brasil.2026.Chappell.Roan.2160p.GLBO.WEB-DL.DDPA5.1.HLG.H.265-JL92.mkv','Chappell Roan','查普尔·罗恩','2026年巴西Lollapalooza音乐节','Lollapalooza Brasil','https://www.setlist.fm/setlist/chappell-roan/2026/autodromo-de-interlagos-sao-paulo-brazil-63410e13.html','Super Graphic Ultra Modern Girl|Femininomenon|After Midnight|Naked in Manhattan|Casual|The Subway|HOT TO GO!|Barracuda|Picture You|Love Me Anyway|The Giver|Red Wine Supernova|Coffee|Good Luck, Babe!|My Kink Is Karma|Pink Pony Club')]
jobs=[]
for slug,filename,artist,zh,event,en,ref,titles in names:
 source=next((DATA/filename).glob('*.mkv'))
 jobs.append(dict(slug=slug,source=str(source),bytes=source.stat().st_size,event=event,event_en=en,artist=artist,artist_zh=zh,reference=ref,catalog=[dict(title=t,artist=artist,artist_zh=zh) for t in titles.split('|')]))
write_json(base.BASE/'jobs.json',jobs)
def one(job):
 folder=base.BASE/job['slug'];folder.mkdir(exist_ok=True)
 m=base.probe(job['source']);write_json(folder/'source-probe.json',m)
 rows=base.transcript(job,float(m['format']['duration']),folder)
 print(job['slug'],'transcribed',len(rows),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(one,jobs))
