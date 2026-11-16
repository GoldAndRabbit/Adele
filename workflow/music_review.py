"""Normalize source-audio event evidence instead of trusting a model's verdict.

Observers sometimes call applause or a cut BEFORE the intro a failure. Conversely
they can say passed while reporting an intro began before the cut. Compare their
actual event times to the selected range and independently prepared caption
clock. Contradictory or incomplete observations remain unresolved.
"""
from pathlib import Path
import fcntl
import re
from workflow.live.paths import read_json,write_json
from workflow.content_check import REVIEW,boundary_identity,check,selection

def observed_outro_end(record,last_vocal):
    """Anchor a mislabeled leading performance to its independently timed vocal.

    End clips sometimes label the current song 'previous' and the next intro
    'target'. The contiguous musical block containing the known last vocal is
    the current outro; a later block after applause is a separate performance.
    """
    relative=last_vocal-record['source_span'][0]
    events=sorted(record['result'].get('events',[]),key=lambda e:e.get('start',0))
    musical=[e for e in events if e.get('owner')!='next' and re.search(
        r'vocal|sing|instrument|music|chord|guitar|piano|synth|band|drum',e.get('description',''),re.I)]
    anchors=[e for e in musical if e['start']-1.5<=relative<=e['end']+1.5]
    if not anchors:return None
    finish=max(e['end'] for e in anchors)
    for event in musical:
        if event['start']<=finish+1 and event['end']>finish:finish=event['end']
    if finish>=record['source_span'][1]-record['source_span'][0]-.5:return None
    return finish

def evaluate(start,end,span,first_vocal,last_vocal):
    a,b=span
    if start.get('planned_cut')!=a or end.get('planned_cut')!=b:
        return {'status':'stale'}
    s=start['result'];e=dict(end['result'])
    reported=e.get('target_music_end')
    if reported is None or end['source_span'][0]+reported<last_vocal-1.5:
        observed=observed_outro_end(end,last_vocal)
        if observed is not None:e['target_music_end']=observed
    if s.get('target_music_start') is None or e.get('target_music_end') is None:
        return {'status':'uncertain','reason':'Missing observed music event boundary'}
    onset=start['source_span'][0]+s['target_music_start']
    finish=end['source_span'][0]+e['target_music_end']
    if not (start['source_span'][0]<=onset<start['source_span'][1] and
            end['source_span'][0]<finish<end['source_span'][1]-.5):
        return {'status':'uncertain','reason':'Event falls outside audio or ends at truncated clip edge'}
    if finish<last_vocal-1.5 or onset>first_vocal+1.5:
        return {'status':'uncertain','reason':'Music events contradict independent vocal/caption timing'}
    if onset<a-.35 or finish>b+.35:
        return {'status':'needs_change','observed_onset':onset,'observed_finish':finish}
    return {'status':'passed','observed_onset':onset,'observed_finish':finish,
            'start_reason':f'原音连续事件中，本曲器乐起点约{onset:.3f}秒，选段从{a:.3f}秒开始，首唱约{first_vocal:.3f}秒；切点在完整音乐开始之前或起点处。',
            'end_reason':f'原音连续事件中，本曲音乐结束约{finish:.3f}秒，最后字幕约{last_vocal:.3f}秒结束；选段结束{b:.3f}秒位于完整唱句和尾奏之后。保留掌声不构成失败。'}

def apply(concert,item,start_path,end_path):
    d=concert.song_dir(item);span=selection(concert,item)['slice']
    records=[read_json(start_path),read_json(end_path)]
    if (Path(selection(concert,item)['source']).suffix.lower()=='.ts' and
            any(r.get('audio_recipe')!='source_clock_async1_v2' for r in records)):
        return {'status':'uncertain','reason':'TS observations need source timestamp gap reconstruction'}
    units=[u for u in read_json(d/'subs/translation/result.json')['units']
           if not u.get('dropped') and u.get('type') not in ('讲话','语气词')]
    if not units:return {'status':'uncertain','reason':'No independently prepared vocal clock'}
    first=span[0]+min(u['start'] for u in units)/1000
    last=span[0]+max(u['end'] for u in units)/1000
    outcome=evaluate(read_json(start_path),read_json(end_path),span,first,last)
    if outcome['status']!='passed':return outcome
    paths=[Path(start_path),Path(end_path)]
    with (d/'reports/content_review.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        review=read_json(d/REVIEW,{})
        if review.get('input')!=boundary_identity(concert,item):
            review={'input':boundary_identity(concert,item),'resolutions':[],'human_approved':False}
        review['music']={'status':'passed','method':'original_audio_events_plus_independent_vocal_clock',
            'start_reason':outcome['start_reason'],'end_reason':outcome['end_reason'],
            'evidence':[str(p.resolve()) for p in paths]+[read_json(p)['audio'] for p in paths]}
        write_json(d/REVIEW,review)
    outcome['content']=check(concert,item)
    return outcome
