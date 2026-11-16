import sys,json,os
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
sys.path.insert(0,str(Path.cwd()/'workflow'))
from workflow.preview_batch import visible
from workflow.subtitle_metadata_batch import BASE,prepare_metadata,save_status,subtitle_audit,summary
from workflow.live.paths import read_json,write_json
from workflow.song.title_translation import translate
from workflow.song.song_translation_workflow import Cache
from workflow.llm import chat_json
for c,it in visible():
 if (BASE/'PAUSED').exists():break
 d=c.song_dir(it);row=read_json(BASE/f'{c.slug}--{it["name"]}.json',{})
 if not any('中文歌名' in x for x in row.get('metadata',{}).get('issues',[])):continue
 try:
  r=read_json(d/'subs/translation/result.json',{})
  if not r:raise ValueError('缺少已有翻译上下文')
  translate(Cache(d/'title_translation_cache.json'),r,d)
  m=prepare_metadata(c,it);a=subtitle_audit(c,it)
  save_status(c,it,metadata=m,subtitles=a,status='needs_review' if m['issues'] or a['issues'] else 'ready_for_review')
  print('TITLE_READY',c.slug,it['name'],flush=True)
 except Exception as e:print('TITLE_FAILED',c.slug,it['name'],str(e),flush=True)
summary()
items=[]
for c,it in visible():
 d=c.song_dir(it);b=read_json(d/'delivery_bundle.json',{}).get('bilibili',{})
 if len(b.get('title',''))>80:
  items.append({'id':c.slug+'--'+it['name'],'full_title':b['title'],'song':it['title'],'artist':it.get('artist'),'concert':c.load('info').get('title_zh')})
for start in range(0,len(items),8):
 if (BASE/'PAUSED').exists():break
 target=BASE/f'title-proposals-{start:03d}.json'
 if target.exists():continue
 batch=items[start:start+8]
 try:
  result=chat_json('你是音乐现场投稿文案编辑。只使用提供的资料，为每项提出80字符以内的B站标题缩句候选。完整保留英文歌名和歌手名字，不切词、不加省略号、不编造昵称。尽量保留年份、中文场次与中英字幕；超长时可以把通用关键词移到标签，并在moved_to_tags记录。多首串烧可以用第一首完整歌名+等N首串烧。无法兼顾80字符时返回needs_manual=true，不强行截断。输出JSON items数组，每项id,title,moved_to_tags,reason,needs_manual。此处仅生成待审核候选，不自动覆盖用户已定模板。',json.dumps(batch,ensure_ascii=False),label='B站标题缩句候选')
  byid={r['id']:r for r in result.get('items',[])}
  rows=[]
  for entry in batch:
   row=byid.get(entry['id'],{'id':entry['id'],'needs_manual':True,'reason':'缺少返回项'})
   row['original_title']=entry['full_title'];row['characters']=len(row.get('title',''));row['length_valid']=0<row['characters']<=80;row['adopted']=False;rows.append(row)
  write_json(target,rows);print('PROPOSALS',start,len(rows),flush=True)
 except Exception as e:print('PROPOSALS_FAILED',start,str(e),flush=True)
print('METADATA_REPAIR_FINISHED',flush=True)
