"""Repair individual source/caption findings without releasing an unchecked song.

Uses actual isolated vocals (when their clock matches the selection), independent
ASR passes and an audio observer. Every exception cites an exact issue and audio;
uncertain findings remain blocked. Existing translations are kept unless their
English sentence actually changes. Only the standard translator builds new text.
"""
from pathlib import Path
from datetime import datetime
import json
import shutil
import subprocess

from rapidfuzz import fuzz
from workflow.live.paths import read_json, write_json
from workflow.content_check import (REPORT, REVIEW, boundary_identity, check, digest,
                                   file_hash, norm, selection, source_identity)
from workflow.content_audio_review import ask, extract

CAPTION_KINDS = {'unsupported_subtitle','missing_subtitle'}

def corroborated(text, start, end, reads, minimum=2):
    """A model's rewrite needs independent vocal ASR support, not its confidence."""
    heard=[]
    for ws in reads:
        actual=norm(' '.join(w['w'] for w in ws if start-.7<=w['s']<=end+.7))
        tokens=set(norm(text).split())-{'a','an','the','i','you','your','me','my','and','or','but','is','to','of','in','on','by'}
        supported=sum(any(fuzz.ratio(t,w)>=82 for w in actual.split()) for t in tokens)
        lexical=not tokens or supported/len(tokens)>=.75
        if actual and lexical and fuzz.partial_ratio(norm(text),actual)>=85:
            heard.append(actual)
    return len(heard)>=minimum

def backup(concert, item, label='content_repair'):
    d = concert.song_dir(item)
    folder = d/'reports'/f'before_{label}_{datetime.now():%Y%m%d-%H%M%S-%f}'
    folder.mkdir(parents=True)
    shutil.copytree(d/'subs',folder/'subs')
    for name in ['song.json','watermark.json',REPORT,REVIEW]:
        p = d/name
        if p.is_file():
            dest = folder/name; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,dest)
    for name in ['vertical_source.json','segments.json']:
        p = concert.dir/name
        if p.is_file(): shutil.copy2(p,folder/name)
    return folder

def assert_idle(concert, item):
    import psutil
    name = item['name']
    for p in psutil.process_iter(['pid','cmdline']):
        args = p.info['cmdline'] or []
        if ('workflow.concert_delivery' in args and '--only' in args and name in args and
                args[args.index('workflow.concert_delivery')+1:][:1]==[concert.slug]):
            raise RuntimeError(f'{name}: rendering assets are frozen; wait for the worker to exit')

def change_cut(concert, item, start, end):
    """Preserve translations and old audio/cache evidence when extending a cut."""
    from workflow.song.trim import shift_subs
    from workflow.song.song_translation_workflow import build_outputs
    from workflow.preview_batch import enable_browser
    from workflow.song.watermark import ensure_song
    assert_idle(concert,item)
    d = concert.song_dir(item); old = selection(concert,item)['slice']
    if [start,end] == old: return None
    if end <= start: raise ValueError('Invalid repaired cut')
    folder = backup(concert,item,'cut_repair')
    write_json(folder/'old-slice.json',old)
    shift_subs(d,start-old[0],end-start)
    build_outputs(d,d/'subs')
    info = read_json(d/'song.json'); info.update(slice=[start,end],preview=[start,end])
    write_json(d/'song.json',info)
    policy = read_json(concert.dir/'vertical_source.json')
    policy['songs'][item['name']]['slice']=[start,end]
    write_json(concert.dir/'vertical_source.json',policy)
    segments = read_json(concert.segments)
    next(r for r in segments['items'] if r['name']==item['name']).update(start=start,end=end)
    write_json(concert.segments,segments)
    # Old isolated audio and its ASR are kept, with their old original clock.
    # The renderer always reads the original. Never relabel old audio as new.
    for name in ['audio.flac','vocals.wav']:
        p=d/name
        if p.is_file(): p.replace(folder/name)
    enable_browser(concert,item)
    ensure_song(concert.slug,item['name'])
    return folder

def translated_units(d, rows, cache_path):
    from workflow.song import song_translation_workflow as st
    result=read_json(d/'subs/translation/result.json');brief=result.get('brief') or {}
    context=st.context_text(brief,st.glossary_for(brief,{},[]))
    context+='\n以下是原音复核后的实际现场字幕。讲话按口语直译；不补录音室歌词，不改写实际原话。'
    reusable={norm(u['orig']):u for u in result['units'] if not u.get('dropped') and
              u.get('v2_final') and u.get('v3_final')}
    pending=[i for i,r in enumerate(rows) if norm(r['text']) not in reusable]
    groups=[[{'orig':rows[i]['text'],'type':rows[i]['type']}] for i in pending]
    zh=st.by_groups(st.Cache(cache_path),'actual_audio_repair',st.P_DRAFT,groups,context,'原音字幕修复') if groups else {}
    translated={i:zh[j][0] for j,i in enumerate(pending)}
    output=[]
    for i,r in enumerate(rows):
        previous=reusable.get(norm(r['text']))
        if previous:
            unit=dict(previous,start=round(r['start']*1000),end=round(r['end']*1000),
                orig=r['text'],type=r['type'],heard=r['text'],verdict='source_audio_verified',reused=True)
            unit.pop('i',None);output.append(unit);continue
        text=translated[i]
        if not text:
            from workflow.live.text_match import INTERJ
            tokens=norm(r['text']).split()
            if tokens and all(t in INTERJ for t in tokens):
                text=r['text'];r=dict(r,type='语气词')
            else:
                retry=st.by_groups(st.Cache(cache_path),'actual_audio_literal_retry',
                    st.P_DRAFT+ '\n每一项必须输出非空中文译文。保留句子内容，不因是不完整短句就省略。',
                    [[{'orig':r['text'],'type':r['type']}]],context,'原音字幕补译')
                text=retry[0][0]
        if not text: raise ValueError('Missing actual-audio translation')
        output.append(dict(start=round(r['start']*1000),end=round(r['end']*1000),orig=r['text'],
            type=r['type'],heard=r['text'],verdict='source_audio_verified',anchor=False,
            v1=text,v2=text,v2_final=text,v3=text,v3_final=text,issues=[],locked=False,reused=False))
    return output

def exact_missing_rows(issues,words,units,references,offset,duration):
    """Restore only exact independently heard reference phrases in subtitle gaps."""
    references={norm(s):s for s in references if len(norm(s).split())>=4}
    rows=[];seen=set()
    for issue in issues:
        if issue['kind']!='missing_subtitle':continue
        window=[w for w in words if issue['start']-.05<=w['s']<=issue['end']+.05]
        for normalized,reference in references.items():
            size=len(normalized.split())
            for i in range(len(window)-size+1):
                chunk=window[i:i+size]
                if norm(' '.join(w['w'] for w in chunk))!=normalized:continue
                a=max(0,chunk[0]['s']-offset-.2);b=min(duration,chunk[-1]['e']-offset+.2)
                if b<=a or any(not u.get('dropped') and u['end']/1000>a+.2 and u['start']/1000<b-.2 for u in units):continue
                key=(normalized,round(a,2),round(b,2))
                if key not in seen:
                    seen.add(key);rows.append({'start':a,'end':b,'text':reference,'type':'歌词'})
    return rows

def merge_intervals(issues, offset, duration):
    windows=[]
    for issue in sorted(issues,key=lambda x:x['start']):
        a=max(0,issue['start']-offset-8); b=min(duration,issue['end']-offset+8)
        if b<=a: continue
        if windows and a<=windows[-1][1]+5 and b-windows[-1][0]<=75:
            windows[-1][1]=max(b,windows[-1][1]);windows[-1][2].append(issue)
        else: windows.append([a,b,[issue]])
    return windows

def remap_resolutions(d,remap):
    """An inserted intro changes row numbers, not previously heard original audio."""
    report=read_json(d/REPORT,{})
    detections={r.get('id'):r for r in report.get('detections',[]) if r.get('id')}
    review=read_json(d/REVIEW,{})
    for resolution in review.get('resolutions',[]):
        issue=detections.get(resolution.get('issue_id'))
        if issue and issue.get('unit') in remap:
            changed={k:v for k,v in issue.items() if k not in ('id','resolution')}
            changed['unit']=remap[issue['unit']]
            resolution['previous_issue_id']=resolution['issue_id']
            resolution['issue_id']=digest(changed)
    if review:write_json(d/REVIEW,review)

def append_actual_rows(d,rows,evidence,cache_path):
    """Translate only newly restored original words; keep all existing versions."""
    if not rows:return
    result=read_json(d/'subs/translation/result.json');old=result['units']
    added=translated_units(d,rows,cache_path)
    for u in added:u['source_evidence']=evidence
    combined=sorted(old+added,key=lambda u:u['start']);ids={id(u):u['i'] for u in old};remap={}
    for i,u in enumerate(combined):
        if id(u) in ids:remap[ids[id(u)]]=i
        u['i']=i
    result['units']=combined
    for key in ('notes','final_notes'):
        result[key]={str(remap[int(k)]):v for k,v in result.get(key,{}).items() if int(k) in remap}
    remap_resolutions(d,remap)
    write_json(d/'subs/translation/result.json',result)
    lines=read_json(d/'subs/lines.json')
    for u in added:lines.append({'start_ms':u['start'],'end_ms':u['end'],'text':u['orig'],
        'qwen':u['heard'],'speech':u['type']=='讲话','verdict':'source_audio_verified','removed':False})
    write_json(d/'subs/lines.json',sorted(lines,key=lambda r:r['start_ms']))
    from workflow.song.song_translation_workflow import build_outputs
    build_outputs(d,d/'subs')

def extend_observed_music(concert,item,start_record,end_record):
    """Conservatively restore observed music, bounded by original sung neighbors.

    Never shortens the prepared performance. A boundary suggestion alone cannot
    erase or replace captions. Any newly covered words are translated separately;
    current source/cross-song checks must pass before the song may be dispatched.
    """
    import math
    from workflow.content_check import identify,lyric_references,source_items
    from workflow.source_lyrics import capture
    import contextlib
    d=concert.song_dir(item);old=selection(concert,item)['slice']
    units=read_json(d/'subs/translation/result.json')['units']
    onset_relative=start_record['result'].get('target_music_start')
    finish_relative=end_record['result'].get('target_music_end')
    if finish_relative is None:
        from workflow.music_review import observed_outro_end
        sung=[u for u in units if not u.get('dropped') and u.get('type') not in ('讲话','语气词')]
        if sung:finish_relative=observed_outro_end(end_record,old[0]+max(u['end'] for u in sung)/1000)
    if onset_relative is None or finish_relative is None:
        return {'status':'uncertain','reason':'Original event boundary could not be grounded; keep this song isolated'}
    onset=start_record['source_span'][0]+onset_relative
    finish=end_record['source_span'][0]+finish_relative
    bank=read_json(d/'reports/source_lyrics_evidence.json')['bank']
    transcript=read_json(Path(bank)/'transcript.json');words=transcript['words']
    refs=lyric_references(concert,source_items(concert,item))
    found=identify([w for w in words if old[0]-100<=w['s']<=old[1]+100],refs,item['name'])
    first=old[0]+min(u['start'] for u in units if not u.get('dropped'))/1000
    last=old[0]+max(u['end'] for u in units if not u.get('dropped'))/1000
    previous=max((m['end'] for m in found if m['owner']!=item['name'] and m['end']<first-1),default=0)
    following=min((m['start'] for m in found if m['owner']!=item['name'] and m['start']>last+1),default=transcript['source_duration'])
    # A neighboring final refrain can contain only one or two words, which the
    # song-identity matcher intentionally cannot classify. Its prepared, audible
    # caption clock still bounds the cut; never pull that last word into this song.
    source=Path(selection(concert,item)['source']).resolve()
    for neighbor in source_items(concert,item):
        if neighbor['name']==item['name']:continue
        neighboring=selection(concert,neighbor)['slice']
        prior_units=read_json(concert.song_dir(neighbor)/'subs/translation/result.json',{}).get('units',[])
        sung=[u for u in prior_units if not u.get('dropped') and u.get('type') not in ('讲话','语气词')]
        if neighboring[0]<old[0]:
            previous=max([previous]+[neighboring[0]+u['end']/1000 for u in sung
                if neighboring[0]+u['end']/1000<first-1])
        else:
            following=min([following]+[neighboring[0]+u['start']/1000 for u in sung
                if neighboring[0]+u['start']/1000>last+1])
    a=min(old[0],max(math.floor(onset-.5),previous+.5))
    b=max(old[1],min(math.ceil(finish+.5),following-.5))
    a=max(0,a);b=min(transcript['source_duration'],b)
    if [a,b]==old:return {'status':'unchanged','reason':'No evidence-supported extension'}
    if old[0]-a>100 or b-old[1]>100:return {'status':'uncertain','reason':'Proposal outside observed guard audio'}
    evidence_folder=d/'reports/music_extension';evidence_folder.mkdir(exist_ok=True)
    record_path=evidence_folder/(digest({'old':old,'new':[a,b]})+'.json')
    write_json(record_path,{'original':old,'repaired':[a,b],'observed_onset':onset,'observed_finish':finish,
        'previous_sung_end':previous,'next_sung_start':following,'start_observation':start_record,
        'end_observation':end_record,'human_review':False})
    change_cut(concert,item,a,b)
    new_units=read_json(d/'subs/translation/result.json')['units'];tokens=[];rows=[]
    new_words=[w for w in words if a<=w['s']<old[0] or old[1]<=w['s']<b]
    # ASR receives no lyric reference. Only newly restored, actually recognized
    # words are added; no absent studio verse is fabricated to fill the range.
    for i,w in enumerate(new_words):
        absolute=w['s'];rel=absolute-a
        visible=[u for u in new_units if u['start']/1000-.3<=rel<=u['end']/1000+.3]
        if any(norm(w['w']) in norm(u['orig']).split() for u in visible):continue
        tokens.append(w);nxt=new_words[i+1] if i+1<len(new_words) else None
        if nxt is None or nxt['s']-w['e']>.8 or len(tokens)>=12 or w.get('punct') in ['.','?','!']:
            if len(tokens)>=2:
                text=' '.join(x['w'] for x in tokens)
                matches=identify(tokens,refs,item['name'])
                kind='歌词' if any(m['owner']==item['name'] for m in matches) else '讲话'
                rows.append({'start':max(0,tokens[0]['s']-a-.2),'end':min(b-a,tokens[-1]['e']-a),
                    'text':text,'type':kind})
            tokens=[]
    append_actual_rows(d,rows,str(record_path.resolve()),evidence_folder/(record_path.stem+'.translation.json'))
    with (evidence_folder/'source-refresh.log').open('a') as log,contextlib.redirect_stdout(log):
        capture(concert,items=[item],workers=2)
    review=read_json(d/REVIEW,{})
    review.update(input=boundary_identity(concert,item),human_approved=False)
    review['music']={'status':'passed','method':'conservative_original_audio_coverage_with_lyric_neighbors',
        'start_reason':f'连续原音事件观察本曲器乐起点约{onset:.3f}秒。范围保守扩展为{a:.3f}秒起，且由独立原片歌词限制在上一曲末词{previous:.3f}秒之后；所有原字幕整体平移，新增范围中实际识别到的原话另外补译。',
        'end_reason':f'连续原音事件观察音乐结束约{finish:.3f}秒，末端保留至{b:.3f}秒，并受下一曲已识别首词{following:.3f}秒约束；没有删除原唱句或以录音室歌词猜补。',
        'evidence':[str(record_path.resolve()),start_record['audio'],end_record['audio']]}
    write_json(d/REVIEW,review)
    return {'status':'repaired','old':old,'new':[a,b],'content':check(concert,item)}

def repair_captions(concert, item):
    """Resolve only per-issue audio decisions; retain uncertain items verbatim."""
    assert_idle(concert,item)
    d=concert.song_dir(item);report=check(concert,item)
    policy=selection(concert,item);offset,end=policy['slice'];duration=end-offset
    original_result=read_json(d/'subs/translation/result.json')
    evidence=read_json(d/'reports/source_lyrics_evidence.json')
    exact=exact_missing_rows(report['issues'],evidence['words'],original_result['units'],
        (d/'lyrics.txt').read_text().splitlines(),offset,duration)
    if exact:
        backup(concert,item,'exact_missing_phrase')
        dest=d/'reports/exact_missing_phrases';dest.mkdir(exist_ok=True)
        proof=dest/(digest(exact)+'.json')
        write_json(proof,{'source':evidence['input']['source'],'source_words':evidence['words'],
            'added':exact,'method':'exact_original_asr_phrase_in_uncovered_gap','human_review':False})
        append_actual_rows(d,exact,str(proof.resolve()),dest/(proof.stem+'.translation.json'))
        report=check(concert,item)
    issues=[x for x in report['issues'] if x['kind'] in CAPTION_KINDS]
    if not issues: return report
    result=read_json(d/'subs/translation/result.json');units=result['units']
    read_paths=sorted((d/'subs').glob('asr_words_*.json'))
    original_reads=[read_json(p) for p in read_paths]
    seen_reads={file_hash(p) for p in read_paths}
    for saved in evidence.get('alternate_reads',[]):
        if (saved.get('origin')=='independent_saved_vocal_asr' and
                saved.get('original_source')==evidence['input']['source'] and
                saved.get('cache_sha256') not in seen_reads):
            seen_reads.add(saved['cache_sha256'])
            original_reads.append([dict(w,s=w['s']-offset,e=w['e']-offset) for w in saved['words']])
    source=policy['source'];local_clock=False
    if (d/'vocals.wav').is_file():
        import soundfile as sf
        if abs(sf.info(d/'vocals.wav').duration-duration)<.3:
            source=str(d/'vocals.wav');local_clock=True
    evidence=read_json(d/'reports/source_lyrics_evidence.json')
    folder=d/'reports/audio_caption_repair';folder.mkdir(exist_ok=True)
    review=read_json(d/REVIEW,{})
    if review.get('input')!=boundary_identity(concert,item):
        review={'input':boundary_identity(concert,item),'resolutions':[],'human_approved':False}
    resolutions=review.setdefault('resolutions',[]);replacements={};additions=[]
    for a,b,group in merge_intervals(issues,offset,duration):
        window_source=source;window_offset=offset if local_clock else 0
        if not local_clock:
            # An extended clip has no new isolated-vocal file. Existing saved
            # vocals still cover most old lines and retain their original clock.
            # Reuse those actual samples instead of falling back to a noisier mix.
            for saved in evidence.get('alternate_reads',[]):
                span=saved.get('source_range');track=saved.get('audio_track',{})
                p=Path(track.get('path','/nonexistent'))
                if (saved.get('origin')=='independent_saved_vocal_asr' and span and
                        saved.get('original_source')==evidence['input']['source'] and
                        span[0]<=offset+a and offset+b<=span[1] and p.is_file() and
                        source_identity(p)==track):
                    window_source=str(p);window_offset=span[0];break
        seek_a=offset+a-window_offset;seek_b=offset+b-window_offset
        current=[u for u in units if not u.get('dropped') and u['end']/1000>=a and u['start']/1000<=b]
        reads=[' '.join(w['w'] for w in ws if a<=w['s']<=b) for ws in original_reads]
        bank=' '.join(w['w'] for w in evidence['words'] if offset+a<=w['s']<=offset+b)
        binding={'source':source_identity(window_source),'range':[a,b],'audio_seek':[seek_a,seek_b],
            'issues':group,'units':current,'reads':reads,'bank':bank}
        key=digest(binding)[:24];audio=folder/(key+'.wav');output=folder/(key+'.json')
        if not audio.exists():extract(window_source,seek_a,seek_b,audio)
        payload={'issues':group,'displayed_units':[dict(i=u['i'],start=u['start']/1000-a,
            end=u['end']/1000-a,text=u['orig'],type=u['type']) for u in current],
            'independent_vocal_ASR':reads}
        if output.exists(): decision=read_json(output)['result']
        else:
            prompt=('Inspect the ACTUAL supplied concert audio, not studio lyrics. All displayed text and ASR below '
                'are fallible hypotheses. Listen for actual words. The clip spans song-relative seconds '
                f'{a:.3f}–{b:.3f}. Returned segment timestamps must be CLIP-RELATIVE, within0–{b-a:.3f}. '
                'For EACH issue ID return status supported (current subtitle is audibly right/already covers phrase), '
                'needs_correction (clear actual words differ or are absent from captions), or uncertain. '
                'Do not declare a real live ad-lib wrong just because studio lyrics differ. Speech also needs captions. '
                'Do not mistake spelled letter chants for missing translation. For supported, quote what is actually '
                'heard and identify covering unit IDs. For needs_correction give ONLY replacement segments for the '
                'erroneous unit or genuinely missing words; do not transcribe the whole clip or repeat other captions. '
                'Use an empty replacement_segments only if the supposed line is clearly not sung/spoken there. '
                'If overlap, backing vocals or audio is unclear, return uncertain rather than inventing words. '
                'Return JSON {"decisions":[{"issue_id":"exact ID","status":"supported/needs_correction/uncertain",'
                '"heard":"actual heard words","reason":"specific audible evidence","confidence":0.0,'
                '"covering_unit_ids":[0],"replacement_segments":[{"start":0.0,"end":1.0,"text":"actual words",'
                '"type":"歌词/讲话/现场即兴"}]}]}. Hypotheses: '+json.dumps(payload,ensure_ascii=False))
            decision=ask(audio,prompt,output)
        record=read_json(output);record['binding']=binding;write_json(output,record)
        for issue in group:
            answer=next((v for v in decision.get('decisions',[]) if v.get('issue_id')==issue['id']),{})
            if answer.get('confidence',0)<.85 or not answer.get('reason'):continue
            if answer.get('status')=='supported':
                # Missing-caption exceptions must identify an actual existing
                # nearby subtitle, rather than merely claiming the song is right.
                owners=[u for u in current if u['i'] in answer.get('covering_unit_ids',[])]
                if issue['kind']=='missing_subtitle' and not owners:continue
                if not answer.get('heard'):continue
                target=next((u['orig'] for u in current if u['i']==issue.get('unit')),'')
                if issue['kind']=='missing_subtitle':target=' '.join(u['orig'] for u in owners)
                if fuzz.partial_ratio(norm(answer['heard']),norm(target))<80:continue
                resolutions.append({'issue_id':issue['id'],'reason':answer['reason'],
                    'method':'machine_actual_audio_adjudication','heard':answer['heard'],
                    'evidence':[str(audio.resolve()),str(output.resolve())],'human_approved':False})
            elif answer.get('status')=='needs_correction':
                segments=answer.get('replacement_segments')
                if segments is None:continue
                valid=[]
                for s in segments:
                    if not (0<=s.get('start',-1)<s.get('end',-1)<=b-a+.1 and s.get('text')):break
                    if s.get('type') not in ('歌词','讲话','现场即兴'):break
                    valid.append(dict(s,start=a+s['start'],end=min(duration,a+s['end'])))
                else:
                    # Audio observers can echo a mistaken mix transcript with
                    # high confidence. Never overwrite a caption on that alone.
                    if not valid or not all(corroborated(s['text'],s['start'],s['end'],original_reads)
                                            for s in valid):
                        proposal=folder/(key+'.unconfirmed.json')
                        write_json(proposal,{'issue':issue,'proposed':valid,'decision':answer,
                            'status':'needs_independent_corroboration','applied':False})
                        continue
                    if issue['kind']=='unsupported_subtitle':
                        replacements[issue['unit']]={'segments':valid,'evidence':str(output.resolve())}
                    elif valid:additions.extend(dict(s,evidence=str(output.resolve())) for s in valid)
    if replacements or additions:
        assert_idle(concert,item)
        backup(concert,item,'caption_repair')
        new=[]
        for u in units:
            repair=replacements.get(u['i'])
            if repair is None:new.append(u);continue
            rows=translated_units(d,repair['segments'],folder/(digest(repair)+'.translation.json')) if repair['segments'] else []
            for row in rows:row['source_evidence']=repair['evidence']
            new.extend(rows)
        if additions:
            rows=translated_units(d,additions,folder/(digest(additions)+'.translation.json'))
            for row,source_row in zip(rows,additions):row['source_evidence']=source_row['evidence']
            new.extend(rows)
        new.sort(key=lambda u:u['start'])
        remap={};old_by_id={id(u):u['i'] for u in units}
        for i,u in enumerate(new):
            if id(u) in old_by_id:remap[old_by_id[id(u)]]=i
            u['i']=i
        result['units']=new
        for key in ('notes','final_notes'):
            result[key]={str(remap[int(k)]):v for k,v in result.get(key,{}).items() if int(k) in remap}
        write_json(d/'subs/translation/result.json',result)
        old_lines=read_json(d/'subs/lines.json',[]);updated=[]
        for u in new:
            old=next((r for r in old_lines if r.get('start_ms')==u['start'] and norm(r.get('text'))==norm(u['orig'])),None)
            updated.append(old or {'start_ms':u['start'],'end_ms':u['end'],'text':u['orig'],
                'qwen':u.get('heard',''),'speech':u['type']=='讲话','verdict':'source_audio_verified','removed':False})
        write_json(d/'subs/lines.json',updated)
        from workflow.song.song_translation_workflow import build_outputs
        build_outputs(d,d/'subs')
    # Deduplicate exact decisions on restart, retaining all original evidence.
    import fcntl
    assert_idle(concert,item)
    with (d/'reports/content_review.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        latest=read_json(d/REVIEW,{})
        if latest.get('input')==review['input']:
            review={**latest,**{k:v for k,v in review.items() if k not in ('music','resolutions')}}
            resolutions=latest.get('resolutions',[])+resolutions
        review['resolutions']=list({r['issue_id']:r for r in resolutions}.values())
        write_json(d/REVIEW,review)
    return check(concert,item)


if __name__=='__main__':
    import argparse
    from workflow.live.paths import Concert
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert');parser.add_argument('songs',nargs='+')
    args=parser.parse_args();c=Concert(args.concert);failed=[]
    for name in args.songs:
        report=repair_captions(c,c.item(name))
        print(name,report['status'],[r['kind'] for r in report['issues']],flush=True)
        if report['status']!='passed':failed.append(name)
    if failed:raise SystemExit('仍需处理：'+', '.join(failed))
