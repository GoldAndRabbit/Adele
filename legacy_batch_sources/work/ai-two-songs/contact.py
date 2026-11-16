from pathlib import Path
import json,subprocess as sp
from PIL import Image,ImageDraw
policy=json.loads(Path('concerts/grammys_2014/vertical_source.json').read_text())['songs']
for name in ['01_drunk_in_love','02_royals']:
 p=policy[name];d=Path('work/ai-two-songs')/name;d.mkdir(exist_ok=True);start,end=p['slice']
 sp.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y','-ss',str(start),'-i',p['source'],'-t',str(end-start),'-vf','bwdif=mode=send_frame:parity=tff:deint=all,fps=1/6,scale=320:180','-q:v','2',str(d/'coarse-%03d.jpg')],check=True)
 files=sorted(d.glob('coarse-*.jpg'));img=Image.new('RGB',(1280,210*((len(files)+3)//4)),(25,25,25));draw=ImageDraw.Draw(img)
 for i,f in enumerate(files):
  x=(i%4)*320;y=(i//4)*210;img.paste(Image.open(f),(x,y));draw.text((x+5,y+182),f'{i+1}: approx +{i*6+3:.1f}s | {start+i*6+3:.1f}s',fill='white')
 img.save(d/'contact.jpg')
 print(name,len(files),flush=True)
