from workflow.live.paths import *
from workflow.posting_cover import active_cover_set
from PIL import Image,ImageDraw,ImageFont
b=ROOT/'work/cover-expression-20261114';c=Concert('singles');out=Image.new('RGB',(1040,1000),'#181c24');draw=ImageDraw.Draw(out);font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',22);progress=read_json(b/'progress.json');manifest=[]
for j,r in enumerate(progress['items']):
 n=r['name'];d=b/n;receipt=read_json(d/'verified.json');assert receipt['posting_json_verified'];i=c.item(n);covers=active_cover_set(c.song_dir(i));title=i['title'];draw.text((j*520+10,4),title[:43],font=font,fill='white')
 for key,pos,box in [(('bili-ai','16x9'),(j*520+4,36),(512,288)),(('douyin-ai','3x4'),(j*520+10,336),(490,653))]:
  im=Image.open(covers[key]);im.thumbnail(box);out.paste(im,pos)
 r['status']='verified';manifest.append(dict(name=n,title=title,source_time=r['source_time'],covers={p+'-'+ratio:str(f) for (p,ratio),f in covers.items()},verified=receipt))
progress['verified']=2;write_json(b/'progress.json',progress);write_json(b/'results.json',manifest);out.save(b/'results.jpg',quality=95)
