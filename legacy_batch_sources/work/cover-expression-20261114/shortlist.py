from workflow.live.paths import *
from PIL import Image,ImageDraw,ImageFont
import subprocess
b=ROOT/'work/cover-expression-20261114';c=Concert('singles');policy=read_json(c.dir/'vertical_source.json')['songs']
for n in ['adele_send_my_love_mv_fk4bbf7b29w','adele_rolling_in_deep_mv_ryeda3jcqqw']:
 d=b/n;d.mkdir(exist_ok=True);out=Image.new('RGB',(1400,12*155),'#181c24');draw=ImageDraw.Draw(out)
 for j,t in enumerate(range(4,233 if 'rolling' in n else 225,4)):
  p=d/f'{t}.jpg'
  if not p.exists():subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',policy[n]['source'],'-frames:v','1','-vf','scale=560:-2','-q:v','2','-y',str(p)],check=True)
  im=Image.open(p);im.thumbnail((276,132));x,y=j%5*280,j//5*155;out.paste(im,(x,y));draw.text((x+4,y+133),str(t),fill='white')
 out.save(d/'contact.jpg',quality=92);print(n,flush=True)
