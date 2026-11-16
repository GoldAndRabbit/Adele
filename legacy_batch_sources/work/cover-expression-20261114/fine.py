from workflow.live.paths import *
from PIL import Image,ImageDraw
import subprocess
b=ROOT/'work/cover-expression-20261114';p=read_json(Concert('singles').dir/'vertical_source.json')['songs']
for n,times in [('adele_send_my_love_mv_fk4bbf7b29w',[i/4 for i in range(608,676)]),('adele_rolling_in_deep_mv_ryeda3jcqqw',[i/4 for i in list(range(52,76))+list(range(300,332))+list(range(516,540))])]:
 d=b/n;out=Image.new('RGB',(1500,((len(times)+5)//6)*168),'#181c24');draw=ImageDraw.Draw(out)
 for j,t in enumerate(times):
  f=d/f'fine-{t}.jpg';subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',p[n]['source'],'-frames:v','1','-vf','scale=960:-2','-q:v','2','-y',str(f)],check=True)
  im=Image.open(f);im.thumbnail((248,144));x,y=j%6*250,j//6*168;out.paste(im,(x,y));draw.text((x+4,y+145),str(t),fill='white')
 out.save(d/'fine.jpg',quality=94)
