import json,subprocess as sp
from pathlib import Path
from PIL import Image,ImageDraw
policy=json.loads(Path('concerts/grammys_2014/vertical_source.json').read_text())['songs']
for name,times in [('01_drunk_in_love',[80,81,82,122,123,124,194,195,196,230,231,232]),('02_royals',[49,50,51,122,123,124,170,171,172,182,183,184])]:
 p=policy[name];d=Path('work/ai-two-songs')/name;img=Image.new('RGB',(1280,810),(24,24,24));dr=ImageDraw.Draw(img)
 for i,t in enumerate(times):
  f=d/f'fine-{t}.jpg';absolute=p['slice'][0]+t
  sp.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','fatal','-y','-ss',str(max(0,absolute-8)),'-i',p['source'],'-ss','8','-vf','bwdif=mode=send_frame:parity=tff:deint=all','-frames:v','1','-q:v','2',str(f)],check=True)
  x=i%4*320;y=i//4*270;im=Image.open(f);im.thumbnail((320,240));img.paste(im,(x,y));dr.text((x+5,y+240),str(t),fill='white')
 img.save(d/'fine-contact.jpg');print(name,'fine ready',flush=True)
