from pathlib import Path
from PIL import Image,ImageDraw
import json,re,os
from urllib.request import urlopen
from workflow.live.paths import Concert,read_json
from workflow.posting_cover import active_cover_set
base=Path(__file__).resolve().parent;url='http://127.0.0.1:8160'
old=(base/'results.md').read_text()
jobs=dict.fromkeys(re.findall(r'\]\(http://127\.0\.0\.1:8160/#/([^/]+)/([^\)]+)\)',old))
fresh={}
for f in base.iterdir():
 if not f.is_dir() or not f.name.isdecimal():continue
 if not any((f/p).is_file() for p in ('release-final/verified.json','stage-reviewed/verified.json','stage/verified.json')):continue
 req=next(f/p for p in ['final.json','reviewed.json','q2.json','q.json'] if (f/p).is_file());q=read_json(req);key=q['slug'],q['name'];fresh[key]=f;jobs[key]=None
cards={};lines=[];records=[]
for s,n in jobs:
 c=Concert(s);it=c.item(n);d=c.song_dir(it);files=active_cover_set(d);ai=d/'covers/ai';m=read_json(ai/'masters.json')[0];key=(s,n)
 p=read_json(c.dir/'vertical_source.json')['songs'][n];t=m['source_time']-p['slice'][0];dy=read_json(d/'vertical/douyin_submission.json');bil=read_json(d/'post/bili_upload.json');bundle=read_json(d/'delivery_bundle.json')
 assert bundle['douyin']['selected_cover']==dy['selected_cover'] and bundle['bilibili']['封面16:9']==bil['封面16:9']
 for path,field in [(bil['封面16:9'],('bili-ai','16x9')),(bil['封面4:3'],('bili-ai','4x3')),(dy['selected_cover']['path'],('douyin-ai','3x4')),(dy['selected_cover']['wide_path'],('douyin-ai','4x3'))]:
  assert os.path.samefile(path,files[field]) or Path(path).read_bytes()==files[field].read_bytes()
 if s not in cards:cards[s]={v['name']:v for v in json.load(urlopen(f'{url}/api/concerts/{s}/album_covers',timeout=30))['covers']}
 for field,k in [(('douyin-ai','3x4'),'portrait_url'),(('bili-ai','16x9'),'url')]:
  assert urlopen(url+cards[s][n][k],timeout=30).read()==files[field].read_bytes()
 if key in fresh:
  rec=next(read_json(fresh[key]/z) for z in ['release-final/verified.json','stage-reviewed/verified.json','stage/verified.json'] if (fresh[key]/z).exists());assert rec['master']==m['file']
 title=it.get('display_title') or it['title'];lines.append(f"| [{title}]({url}/#/{s}/{n}) · {n if s=='singles' else s} | "+('重新选帧生图' if key in fresh else '竖版重裁')+f" | {int(t//60)}:{t%60:04.1f} | "+(f"{m['generation_seconds']:.1f} 秒 | {m['peak_process_gb']:.2f} GB" if key in fresh else '— | —')+' |');records.append((key,title,ai,m,files['douyin-ai','3x4']))
print('VERIFIED',len(records),'regenerated',len(fresh),flush=True)
head=['# 竖版封面复核','',f'共 38 个调整条目，覆盖 45 个视频版本。已核验 {len(records)} / 45，其中 {len(fresh)} 个重新选帧生成，{len(records)-len(fresh)} 个竖版重裁。已校验专辑预览实际图片、B站和抖音投稿 JSON、交付文件。','','| 歌曲与版本 | 处理 | 选帧位置（单曲） | 生图耗时 | 峰值内存 |','|---|---|---:|---:|---:|']
(base/'results.md').write_text('\n'.join(head+lines)+'\n')
freshrows=[r for r in records if r[0] in fresh];sheet=Image.new('RGB',(900,155*len(freshrows)),'#22252b');draw=ImageDraw.Draw(sheet)
for j,(key,title,ai,m,pic) in enumerate(freshrows):
 for x,path in [(0,ai/m['original_reference']),(335,ai/m['file']),(710,pic)]:
  tile=Image.open(path);tile.thumbnail((320,127));sheet.paste(tile,(x,j*155))
 draw.text((3,j*155+129),f"{title[:44]}   {m['generation_seconds']:.1f}s   {m['peak_process_gb']:.2f}GB")
sheet.save(base/'regenerated.jpg',quality=93)
sheet=Image.new('RGB',(6*174,((len(records)+5)//6)*250),'#22252b');draw=ImageDraw.Draw(sheet)
for j,(key,title,ai,m,pic) in enumerate(records):
 tile=Image.open(pic);tile.thumbnail((163,217));x=j%6*174;y=j//6*250;sheet.paste(tile,(x,y));draw.text((x,y+218),title[:24])
sheet.save(base/'covers.jpg',quality=92)
