from pathlib import Path
import sys,json,os,re,itertools,shutil,fcntl,time
from concurrent.futures import ThreadPoolExecutor
R=Path(__file__).resolve().parents[2];B=Path(__file__).resolve().parent;sys.path[:0]=[str(R),str(R/'workflow')]
from workflow.llm import chat_json
from post_bili import upload
from post_bili.metadata_quality import issues,fingerprint
from types import SimpleNamespace
lock=(B/'copy_review.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
def put(p,v):
 t=p.with_name('.'+p.name+'.copytmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2));t.replace(p)
def load(p):return json.loads(p.read_text()) if p.is_file() else {}
def backup(p,b):
 if p.is_file() and not (b/p.name).exists():shutil.copy2(p,b/p.name)
def run(row):
 d=Path(row['directory']).resolve();n=d.name
 if load(d/'copy_review_status.json').get('stage') in ('verified','posted_edit_proposed'):return
 b=d/'copy_backup_20261104';b.mkdir(exist_ok=True)
 try:
  p=d/'post'/f'{n}.json'
  if not p.exists():p=d/'post_draft.json'
  data=load(p);policy=load(d/'metadata_policy.json');event=policy.get('required_event')
  mat={k:data.get(k) for k in ['song','performance','title','intro','intro_text','tags']};mat['内容依据']=load(d/'subs/translation/result.json').get('brief',{})
  mat['画面记录']=load(d/'stage_notes.json');mat['场次要求']=event;mat['已知艺名及演出']=load(d/'presentation_preferences.json')
  src=json.dumps(mat,ensure_ascii=False)[:19000];note=''
  for attempt in range(3):
   v=chat_json('你为音乐现场写中文投稿文案。严格依据提供的本场资料，不编造奖项、榜单、演出动作、首演或销量。写给观众，不提制作技术或审校过程。JSON返回 titles（6种清楚简短的完整投稿标题，含[4K60帧/Hi-Res]、主要歌手、《歌名》、真实演出名和中英字幕，格莱美必须完整写2014第56届格莱美颁奖典礼，串烧可简写两首名），paragraphs（6至8段，总计约2100个中文字符，分述歌曲、歌手、此版本和歌词主题，每段有具体信息，不重复，不大段引用歌词），tags（16个不同且具体相关的候选标签，优先中英文艺名、演出、歌曲）。不得用无关关键词凑字。',src+note,temperature=.3,label=n)
   old=data.get('title','');candidates=[old]+v['titles'];title=None
   for base in candidates:
    if not isinstance(base,str) or not base.startswith('[4K60帧/Hi-Res]') or not base.endswith('中英字幕') or (event and event not in base):continue
    if 78<=len(base)<=80:title=base;break
    for count in (1,2):
     for words in itertools.combinations(['现场演唱','双语精校','欧美现场','Grammy' if event else '音乐现场'],count):
      if any(w in base for w in words):continue
      t=base[:-4].rstrip()+' '+' '.join(words)+' 中英字幕'
      if 78<=len(t)<=80:title=t;break
     if title:break
    if title:break
   desc='\n\n'.join(x.strip() for x in v['paragraphs'] if isinstance(x,str))
   if len(desc)<1810:
    extra=chat_json('根据同一首歌的演出资料，续写独立的歌词含义和演唱诠释段落。只作文本解读，不能编造现场细节，不复述前文，不添加标题。给6段，每段200个中文字符，返回 JSON 对象 {"paragraphs":[...]}。',src+'\n已有简介：'+desc,temperature=.4,label='补充简介 '+n)
    desc+='\n\n'+'\n\n'.join(z.strip() for z in extra['paragraphs'] if isinstance(z,str))
   if len(desc)>2000:
    pos=max(desc.rfind(c,1800,2000) for c in '。！？')
    desc=desc[:pos+1] if pos>=0 else ''
   tags=[];prefs=mat['已知艺名及演出'].get('tags') or []
   for t in ['音乐分享官',event,*prefs,*v['tags'],*data.get('tags',[])]:
    if isinstance(t,str) and 0<len(t.strip())<=20 and t.strip().casefold() not in {x.casefold() for x in tags}:tags.append(t.strip())
   tags=tags[:12];fields=dict(title=title or '',desc=desc,tag=tags);err=issues(fields,policy,require_review=False)
   if err:note='\n上一稿退回：'+'；'.join(err);continue
   verdict=chat_json('根据资料审查投稿文案。标题必须对应实际歌手、曲目与演出， tags 必须有歌手和演出名且全部贴题。简介应确实讲到歌曲、该版本及歌词主题，无编造事实、通用套话或重复。不要用猜测来肯定具体细节。返回 JSON {ok:布尔值,reason:字符串}。',src+'\n待审稿：'+json.dumps(fields,ensure_ascii=False),temperature=.1,label='稿件复核 '+n)
   if verdict.get('ok') is not True:note='\n上一稿退回：'+str(verdict.get('reason'));continue
   # Preserve posted receipts and the actual submitted JSON; proposals for posted videos are separate.
   posted=bool(load(d/'post/publish.json').get('bvid'));put(d/'reviewed_copy.json',{**fields,'posted':posted,'review':verdict})
   for path in [p,d/'presentation_preferences.json',d/'post/bili_upload.json']:backup(path,b)
   if not posted:
    data.update(title=title,intro_text=desc,tags=tags);put(p,data)
    pref=load(d/'presentation_preferences.json');pref['tags']=tags;put(d/'presentation_preferences.json',pref)
    args=SimpleNamespace(cover=None,source=None,at=None,tid=None,tid_v2=None,only_self=False)
    cf=upload.generate(d,args);actual=upload.from_page(cf)
    policy['reviewed_fingerprint']=fingerprint(title,desc,tags)
    if issues(actual,policy):raise ValueError(str(issues(actual,policy)))
    put(d/'post/bili_upload.json',cf);put(d/'metadata_policy.json',policy)
   put(d/'copy_review_status.json',{'stage':'posted_edit_proposed' if posted else 'verified','title_length':len(title),'description_length':len(desc),'tag_count':len(tags)});return
  raise ValueError(note)
 except (Exception,SystemExit) as e:put(d/'copy_review_status.json',{'stage':'held','reason':type(e).__name__+': '+str(e)[:220]})
rows=load(B/'status.json')['items'];rows.sort(key=lambda r:(not r['spec'].endswith('18b_open_your_heart'),r['status']=='submitted',r['status']!='waiting_for_metadata'))
with ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(run,rows))
