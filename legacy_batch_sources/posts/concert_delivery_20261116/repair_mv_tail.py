"""Correct the MV comedy coda from independently heard source speech."""
from pathlib import Path
import json, shutil
from rapidfuzz import fuzz
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_check import norm,check
from workflow.song import song_translation_workflow as st

BASE=Path(__file__).parent
NAME='khalid_young_dumb_broke_mv_ipfjnp1gupc'
c=Concert('singles');it=c.item(NAME);d=c.song_dir(it)
result_path=d/'subs/translation/result.json'
result=read_json(result_path)
words=[w for w in read_json(d/'reports/source_lyrics_evidence.json')['words'] if w['s']>=218]
heard=read_json(BASE/'mv-tail-review.json')['result']['sentences']
aligned=[]
for sentence in heard:
    target=norm(sentence['text']);n=len(target.split());expected=218+sentence['start'];choices=[]
    for i,w in enumerate(words):
        if abs(w['s']-expected)>5:continue
        for size in range(max(1,n-2),n+3):
            chunk=words[i:i+size]
            if len(chunk)!=size:continue
            score=fuzz.ratio(target,norm(' '.join(w['w'] for w in chunk)))
            choices.append((score-abs(chunk[0]['s']-expected)*.2,score,chunk))
    _,score,chunk=max(choices,key=lambda row:row[0])
    if score<85:raise ValueError('Independent audio and ASR do not agree: '+sentence['text'])
    aligned.append(dict(sentence,start_ms=round(chunk[0]['s']*1000),end_ms=round(chunk[-1]['e']*1000),asr_agreement=score))

backup=BASE/'mv-tail-before'
if not backup.exists():
    backup.mkdir()
    for path in [result_path,d/'subs/lines.json',*sorted((d/'subs').glob('lyrics*.ass'))]:
        shutil.copy2(path,backup/path.name)

groups=[[{'orig':s['text'],'type':'讲话'}] for s in aligned]
brief=result.get('brief') or {}
context=st.context_text(brief,st.glossary_for(brief,{},[]))
context+='\n这是官方MV结尾校工角色自言自语与模仿哼唱，按实际原话翻译，不套主歌歌词，不添加解释。语气自然口语，保留原话意义。'
translated=st.by_groups(st.Cache(BASE/'mv-tail-translation-cache.json'),'coda_speech',st.P_DRAFT,groups,context,'MV尾声讲话')
kept=[u for u in result['units'] if u['start']<218000]
for j,sentence in enumerate(aligned):
    zh=translated[j][0]
    if not zh:raise ValueError('Missing coda translation')
    kept.append({'i':len(kept),'start':sentence['start_ms'],'end':sentence['end_ms'],
        'orig':sentence['text'],'type':'讲话' if sentence['type']=='speech' else '现场即兴',
        'heard':sentence['text'],'anchor':False,'verdict':'source_audio_verified',
        'v1':zh,'v2':zh,'v2_final':zh,'v3':zh,'v3_final':zh,'issues':[],
        'locked':False,'reused':False,'source_evidence':str((BASE/'mv-tail-review.json').resolve())})
result['units']=kept
write_json(result_path,result)
rows=[r for r in read_json(d/'subs/lines.json',[]) if r.get('start_ms',0)<218000]
for u in kept:
    if u['start']>=218000:
        rows.append({'start_ms':u['start'],'end_ms':u['end'],'text':u['orig'],
                     'qwen':u['orig'],'speech':u['type']=='讲话','verdict':'speech' if u['type']=='讲话' else 'live'})
write_json(d/'subs/lines.json',rows)
st.build_outputs(d,d/'subs')
write_json(BASE/'mv-tail-correction.json',{'status':'corrected','method':'independent_original_audio_plus_word_timestamp_agreement',
           'sentences':aligned,'human_approved':False})
report=check(c,it)
print('MV content check',report['status'],report['issues'],flush=True)
