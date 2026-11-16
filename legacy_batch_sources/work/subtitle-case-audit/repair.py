"""Repair display casing without changing lyric words, translations or timestamps."""
import os,json,re,shutil,traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from llm import chat_json,load_env
from workflow.live.paths import Concert,read_json,write_json
from workflow.subtitle_spelling import sentence_case,display_english
import pysubs2
BASE=Path('work/subtitle-case-audit')
load_env();os.environ['TRANSLATE_MODEL']='deepseek-v4-flash';os.environ.pop('LLM_EFFORT',None)

def one(row):
 c=Concert(row['concert']);it=c.item(row['name']);d=c.song_dir(it);sub=d/'subs'
 status_path=BASE/(c.slug+'--'+it['name']+'.status.json')
 if status_path.exists():return read_json(status_path)
 units=read_json(sub/'translation/result.json')['units'];lines=read_json(sub/'lines.json',[])
 old=list(dict.fromkeys(s for s in [*(u.get('orig','') for u in units),*(r.get('text','') for r in lines)] if s.isupper() and re.search('[A-Za-zÀ-ÿ]',s)))
 cache=BASE/(c.slug+'--'+it['name']+'.json')
 if not cache.exists():
  result=chat_json('你是歌词字幕大小写编辑。输入是同一现场的字幕行。只修改大小写，将全大写句子改为自然句子格式，句首、I和专有名词应大写，DJ、LA、VIP、DNA、APT等缩写保留。不得改任何单词、空格、标点、重复、缩写或拼写错误，不得增删字符。英语和西班牙语均遵循该语言的正常大小写。严格按输入顺序返回 JSON {"lines":[...]}。',json.dumps({'song':it['title'],'artist':it.get('artist'),'lines':old},ensure_ascii=False),temperature=.1,label='字幕大小写 '+it['name'])
  new=result.get('lines',[])
  if len(new)!=len(old) or any(not isinstance(b,str) for b in new):
   raise ValueError('Casing edit returned wrong row count')
  cleaned=[]
  for a,b in zip(old,new):
   letters_a=''.join(x for x in a if x.isalpha())
   letters_b=''.join(x for x in b if x.isalpha())
   if a.casefold()==b.casefold():cleaned.append(b)
   elif letters_a.casefold()==letters_b.casefold() and len(letters_a)==len(letters_b):
    letters=iter(letters_b);cleaned.append(''.join(next(letters) if x.isalpha() else x for x in a))
   else:cleaned.append(sentence_case(a))
  write_json(cache,dict(zip(old,cleaned)))
 mapping=read_json(cache)
 assert set(mapping)==set(old)
 assert all(a.casefold()==b.casefold() for a,b in mapping.items())
 backup=d/'reports/before_case_normalization'
 if not backup.exists():
  backup.mkdir(parents=True)
  shutil.copytree(sub,backup/'subs')
 for r in lines:
  if r.get('text') in mapping:r['text']=mapping[r['text']]
 result=read_json(sub/'translation/result.json')
 for u in result['units']:
  if u.get('orig') in mapping:u['orig']=mapping[u['orig']]
 write_json(sub/'lines.json',lines);write_json(sub/'translation/result.json',result)
 # Update existing subtitle files in place, keeping their styles and notes.
 variants={}
 for a,b in mapping.items():
  variants[a]=b
  # Existing exports expand the few sung elisions supported by display_english.
  from workflow.subtitle_spelling import _ELIDED
  variants[_ELIDED.sub(lambda m:m[1]+'G',a)]=display_english(b)
 changed=0
 for p in sub.iterdir():
  if p.suffix not in ('.ass','.srt') or not p.stat().st_size:continue
  ass=pysubs2.load(str(p))
  for e in ass.events:
   if e.style=='Note':continue
   parts=e.text.split(r'\N')
   for idx,part in enumerate(parts):
    trimmed=part.strip()
    if trimmed in variants:
     parts[idx]=part.replace(trimmed,variants[trimmed]);changed+=1
    elif re.search('[A-Za-z]',part) and part.isupper() and not re.search('[\u3400-\u9fff{}]',part):
     parts[idx]=sentence_case(part)
   e.text=r'\N'.join(parts)
  ass.save(str(p))
 # Prove this change only adjusted case in canonical subtitle fields.
 old_result=read_json(backup/'subs/translation/result.json')
 assert len(old_result['units'])==len(result['units'])
 for a,b in zip(old_result['units'],result['units']):
  assert a['orig'].casefold()==b['orig'].casefold()
  assert {k:v for k,v in a.items() if k!='orig'}=={k:v for k,v in b.items() if k!='orig'}
 status=dict(concert=c.slug,name=it['name'],changed_lines=len(mapping),changed_events=changed,status='ready',link=f'http://127.0.0.1:8160/#/{c.slug}/{it["name"]}')
 write_json(BASE/(c.slug+'--'+it['name']+'.status.json'),status)
 print(json.dumps(status,ensure_ascii=False),flush=True)
 return status

def safe(row):
 try:return one(row)
 except Exception as exc:
  traceback.print_exc();return dict(**row,error=str(exc),status='failed')

if __name__=='__main__':
 rows=read_json(BASE/'inventory.json')['items']
 with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(safe,rows))
 write_json(BASE/'results.json',results)
