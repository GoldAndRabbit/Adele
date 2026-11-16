import json,pathlib,re,subprocess,sys
from PIL import Image
from workflow.song.song_translation_workflow import build_outputs
from workflow import make_cover as mc
root=pathlib.Path.cwd();batch=root/'posts/next_batch_20261031'
jobs=[{'name':'next_20261031_'+x} for x in ['yw7hhsr5uyy','hckfn9jkrr0','gdsukphmb3y','kdorky_13ak','g6fuwd4wnd8','hjbo__1n8li','pilcn6vo_ru','mjrdywp5nye','bv1bepwztepx','bv1qynkz2emk']]
years=[2013,2022,2022,2025,2026,2023,2020,2017,2016,2015]
nums=['XLVII','LVI','LVI','LIX','LX','LVII','LIV','LI','50','XLIX']
casts=['碧昂丝 & 真命天女','德瑞博士 & 史努比狗狗 & 埃米纳姆 & 玛丽·布莱姬 & 肯德里克·拉马尔 & 五角','德瑞博士 & 史努比狗狗 & 埃米纳姆 & 玛丽·布莱姬 & 肯德里克·拉马尔 & 五角','喇嘛 Kendrick Lamar & 诗莎 SZA','坏兔子 & Lady Gaga & 瑞奇·马丁','蕾哈娜','夏奇拉 & 詹妮弗·洛佩兹 & 坏兔子 & 杰·巴尔文 & 艾米·穆尼兹','Lady Gaga','酷玩乐队 & 碧昂丝 & 火星哥布鲁诺·马尔斯','水果姐 & 米西·埃利奥特 & 莱尼·克拉维茨']
cover_cast_overrides={'next_20261031_hjbo__1n8li':'蕾哈娜 Rihanna'}
jobs.append({'name':'next_20261031_ziwkheqvq4s'})
years.append(2019);nums.append('LIII');casts.append('魔力红 & 特拉维斯·斯科特 & 大人物')
jobs.append({'name':'next_20261031_2z3euy1axdy'})
years.append(2018);nums.append('LII');casts.append('贾老板 Justin Timberlake')
jobs.append({'name':'next_20261031_jn2kgdpozz4'})
years.append(2014);nums.append('XLVIII');casts.append('火星哥 Bruno Mars & 红辣椒乐队')
mc.default_cover_event=lambda a:None
mc.FONTS["cjk"]=("/System/Library/Fonts/STHeiti Medium.ttc",0)
for j,year,num,cast in zip(jobs,years,nums,casts):
 if len(sys.argv)>1 and j['name'] not in sys.argv[1:]:continue
 n=j['name'];d=root/'posts'/n;cn=f'{year}超级碗中场秀';en=f'Super Bowl {num} Halftime Show'
 f=d/'title_translation.json';record=json.loads(f.read_text());record.update(title=en,title_zh=cn,artist_zh=cast,source='user-reviewed-cast');f.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
 f=d/'zh_fixed.json';fixed=json.loads(f.read_text()) if f.exists() else {};fixed['__title__']=cn;f.write_text(json.dumps(fixed,ensure_ascii=False,indent=2)+'\n')
 f=d/'subs/translation/result.json';res=json.loads(f.read_text());res['title']=f'《{en}》';res['title_zh']=f'《{cn}》 {cast}';f.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n');build_outputs(d,d/'subs')
 for f in [d/'post'/f'{n}.json',root/'concerts/singles/songs'/n/'post_draft.json']:
  data=json.loads(f.read_text());data['song'].update(title=en,title_zh=cn,artist=cast,artist_zh=cast);f.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 out=d/'post/cover';groups={}
 for f in sorted(out.glob('frame_*.jpg')):
  m=re.match(r'frame_(?:(closeup|half|full|scene|pool)_)?(\d\d)_',f.name)
  if not m:continue
  kind=m[1] or 'cover';img=Image.open(f).convert('RGB');c,c43=mc.compose_pair(img,['--name',n,'--title',cn,'--subtitle',cover_cast_overrides.get(n,cast)+' · 中英字幕']);c.save(out/f'{kind}_{m[2]}.jpg',quality=95);c43.save(out/f'{kind}_{m[2]}_4x3.jpg',quality=95);groups.setdefault(kind,[]).append((c,c43))
 for kind,pairs in groups.items():
  stem='candidates' if kind=='cover' else 'candidates_'+kind
  mc.contact_sheet([x for x,_ in pairs],cols=4).save(out/f'{stem}.jpg',quality=92);mc.contact_sheet([x for _,x in pairs],cols=4).save(out/f'{stem}_4x3.jpg',quality=92)
 print(n,'updated',sum(len(x) for x in groups.values()),flush=True)
