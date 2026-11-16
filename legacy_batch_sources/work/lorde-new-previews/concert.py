import sys,os
from pathlib import Path
root=Path.cwd()
sys.path[:0]=[str(root),str(root/'workflow'),str(root/'work/external-concerts-followup')]
import run as r
os.chdir(root);r.ROOT=root;r.BASE=root/'work/lorde-new-previews'
r.load_env()
s=Path('/Volumes/harddisk_5T/adele-workflow/sources/concerts/lorde_glastonbury_2025/source.mkv')
titles='Hammer|What Was That|Shapeshifter|Man of the Year|Favourite Daughter|Current Affairs|Clearblue|GRWM|Broken Glass|If She Could See Me Now|David|Ribs|Green Light'.split('|')
job=dict(slug='lorde_glastonbury_2025',source=str(s),bytes=s.stat().st_size,event='2025年格拉斯顿伯里音乐节',event_en='Glastonbury Festival',artist='Lorde',artist_zh='洛德',reference='https://www.bilibili.com/video/BV1ugK6z8EMu/',catalog=[dict(title=t,artist='Lorde',artist_zh='洛德') for t in titles])
print(r.produce(job),flush=True)
