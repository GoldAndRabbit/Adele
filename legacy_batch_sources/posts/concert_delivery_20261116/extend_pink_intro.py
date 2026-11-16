"""Preserve the already translated song, adding the audibly missing intro."""
from pathlib import Path
import shutil, contextlib
from workflow.live.paths import Concert,read_json,write_json
from workflow.song.trim import shift_subs
from workflow.song.song_translation_workflow import build_outputs
from workflow.preview_batch import enable_browser
from workflow.source_lyrics import capture
from workflow.content_check import boundary_identity,check,REVIEW
from workflow.song.watermark import ensure_song

BASE=Path(__file__).parent
c=Concert('chappell_lowlands_2025');it=c.item('16_pink_pony_club');d=c.song_dir(it)
old=read_json(c.dir/'vertical_source.json')['songs'][it['name']]['slice']
start,end=4519.0,old[1]
backup=BASE/'boundary-before'/c.slug/it['name']
if not backup.exists():
    backup.mkdir(parents=True)
    shutil.copytree(d/'subs',backup/'subs')
    for rel in ['song.json','watermark.json','reports/boundary_review.json','reports/content_check.json']:
        p=d/rel
        if p.is_file():
            (backup/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,backup/rel)
    write_json(backup/'old-slice.json',old)
    if start>=old[0]:raise ValueError('This repair only extends the existing source, never truncates')
    shift_subs(d,start-old[0],end-start)
    build_outputs(d,d/'subs')
    info=read_json(d/'song.json');info.update(slice=[start,end],preview=[start,end]);write_json(d/'song.json',info)
    policy=read_json(c.dir/'vertical_source.json');policy['songs'][it['name']]['slice']=[start,end];write_json(c.dir/'vertical_source.json',policy)
    segments=read_json(c.segments)
    next(r for r in segments['items'] if r['name']==it['name']).update(start=start,end=end)
    write_json(c.segments,segments)
    # Keep old isolated audio with its original clock; do not present it as the
    # newly extended source. Rendering reads the original full concert directly.
    for rel in ['audio.flac','vocals.wav']:
        p=d/rel
        if p.is_file():p.replace(backup/rel)
enable_browser(c,it)
ensure_song(c.slug,it['name'])
with (BASE/'pink-evidence-refresh.log').open('a') as log,contextlib.redirect_stdout(log):
    capture(c,items=[it],workers=2)
identity=boundary_identity(c,it)
observations=BASE/'music-reviews-v2'/c.slug/it['name']/'onsets.json'
write_json(d/REVIEW,{'input':identity,'music':{'status':'passed',
    'method':'machine_original_audio_event_review',
    'start_reason':'原音4465–4565秒连续片段：上一曲唱句在4482.48秒前结束，随后掌声；新曲马嘶效果约4520.36秒、器乐段约4524.24秒开始。起点改为4519秒，完整保留该前奏，旧字幕只整体后移21秒。',
    'end_reason':'原片4800秒的计划结尾位于本曲音乐结束后的欢呼与讲话，未截断唱句或尾奏；两个音频复核均确认尾部音乐已停。',
    'evidence':[str(observations.resolve()),str((observations.parent/'head.wav').resolve()),str((observations.parent/'audio-review.json').resolve())]},
    'resolutions':[],'human_approved':False})
report=check(c,it);print('Extended intro',old,'->',[start,end],report['status'],report['issues'],flush=True)
if report['status']=='passed':
    import fcntl
    with (BASE/'config.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        config=read_json(BASE/'queue.json');config['blocked_jobs'].pop(c.slug+'/'+it['name'],None);write_json(BASE/'queue.json',config)
