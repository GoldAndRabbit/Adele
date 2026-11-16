from pathlib import Path
import json,subprocess as s,time
from PIL import Image,ImageDraw
w=Path('/Volumes/harddisk_5T/adele-workflow/products/grammys_2014/04_dark_horse/20261106');out=Path('work/dual-dark-horse')
for kind,file,scale in [('portrait','douyin-1080p60.mp4','540:960'),('landscape','bilibili-4k60.mp4','1280:720')]:
 for label,t in [('note',17),('watermark',85.3),('lyric',140),('ending',207.5)]:
  s.run(['/opt/homebrew/bin/ffmpeg','-v','error','-y','-ss',str(t),'-i',str(w/file),'-frames:v','1','-vf','scale='+scale,str(out/f'{kind}-{label}.png')],check=True)
print('Inspection frames ready')
