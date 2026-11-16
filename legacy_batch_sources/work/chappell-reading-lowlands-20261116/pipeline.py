"""Scoped two-Mac review preparation, using the project's production workflows.

One serial song consumer per Mac. This batch never renders final videos,
publishes a post or marks a subtitle as human-approved.
"""
import fcntl
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

ROOT = Path('/Users/gold/repos/adele')
sys.path[:0] = [str(ROOT), str(ROOT/'workflow')]
os.chdir(ROOT)
from workflow.live.paths import Concert, VENV_PY, SEP_PY, read_json, write_json, slugify
from workflow.browser_library import probe
from workflow.preview_batch import enable_browser
from workflow.subtitle_metadata_batch import subtitle_audit, prepare_metadata
from workflow.delivery_bundle import write_bundle
from workflow.live.package import draft_meta
from workflow.ai_cover import reviewed_revision
from workflow.fibo_concert import generate_one
from workflow.fibo_reference import reselect
from workflow.cover_visual_review import review as visual_review
from workflow.reviewed_cover import publish, verify_release, digest
from workflow.song.title_translation import resolved, save as save_title
from workflow.live.segment import norm

BASE = Path(__file__).resolve().parent
STATE = threading.Lock()
PRIMARY = threading.Lock()
ALIGNMENT = threading.Lock()
PREVIEW = threading.Lock()
SSH = ['ssh', '-oBatchMode=yes', '-oConnectTimeout=10', '-i',
       '/Users/gold/.ssh/adele_render_worker', 'zhaojing@192.168.3.10']
REMOTE = 'Library/Caches/adele/subtitle-worker'

# Reuse the established source-ASR locator and reference acquisition code in
# an isolated module instance; never inherit another batch's pause/status files.
spec = importlib.util.spec_from_file_location('_reading_lowlands_locator', ROOT/'work/external-concerts-followup/run.py')
locator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locator)
locator.ROOT = ROOT
locator.BASE = BASE
locator.load_env()


def checkpoint():
    if (BASE/'PAUSED').exists():
        raise RuntimeError('Batch paused')


locator.checkpoint = checkpoint


def state(slug, name='_concert', **values):
    if values.get('status') in ('running','needs_human_review','pass_complete_review_pending') and 'error' not in values:
        values['error']=None
    with STATE:
        path = BASE/'status.json'
        rows = read_json(path, {})
        key = slug+'/'+name
        rows[key] = dict(rows.get(key, {}), **values, updated_at=datetime.now().astimezone().isoformat())
        write_json(path, rows)
    print(slug, name, values, flush=True)


def initialize(job):
    c = Concert(job['slug']);c.dir.mkdir(parents=True, exist_ok=True)
    folder = BASE/c.slug;folder.mkdir(exist_ok=True)
    media = probe(Path(job['source']));write_json(folder/'source-probe.json',media)
    video = next(s for s in media['streams'] if s['codec_type']=='video')
    audio = next(s for s in media['streams'] if s['codec_type']=='audio')
    from fractions import Fraction
    info = {key:job[key] for key in ('slug','artist','artist_zh','date','city','venue','broadcast')}
    info.update(source_file=job['source'],title=job['event'],title_zh=job['event'],title_en=job['event_en'],
                setlist_url=job['reference'],duration=float(media['format']['duration']),width=video['width'],
                height=video['height'],fps_str=video['r_frame_rate'],fps=float(Fraction(video['r_frame_rate'])),
                video_codec=video['codec_name'],audio_codec=audio['codec_name'],audio_channels=audio['channels'])
    if job.get('embedded_captions'):info['source_scope']='edited_broadcast'
    write_json(c.info,info)
    if not c.setlist.exists():
        items=[dict(idx=i,name=f'{i:02d}_{slugify(row["title"])}',title=row['title'],artist=job['artist'],
                    artist_zh=job['artist_zh'],parts=[row['title']],kind='song',review_hidden=True,
                    notes='原曲 Heart' if row['title']=='Barracuda' else '')
               for i,row in enumerate(job['catalog'],1)]
        write_json(c.setlist,{'source':job['reference'],'items':items})
    for item in c.song_items():c.make_song_dir(item)
    return c,folder,info


def transcript(job, folder, duration):
    if (folder/'transcript.json').exists():return read_json(folder/'transcript.json')
    if job.get('embedded_captions'):
        import pysubs2
        target=folder/'source-captions.srt'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',job['source'],'-map','0:s:0',str(target)],check=True)
        captions=pysubs2.load(str(target));rows=[]
        for start in range(0,int(duration)+1,20):
            text=' '.join(e.plaintext for e in captions if start*1000<=e.start<(start+20)*1000)
            rows.append({'t':start,'end':min(start+20,duration),'text':text})
        if sum(bool(r['text'].strip()) for r in rows)>20:
            write_json(folder/'transcript-origin.json',{'source':'embedded source captions; song-level ASR still required'})
            write_json(folder/'transcript.json',rows);return rows
    return locator.transcript(job,duration,folder)


def references(c,item):
    d=c.song_dir(item)
    if (d/'lyrics.txt').is_file() and (d/'lyrics_source').is_file() and not (d/'lyrics_source').read_text().startswith('source-asr'):
        return
    old=Concert('chappell_lolla_brasil_2026')
    match=next((row for row in old.song_items() if norm(row['title'])==norm(item['title'])),None)
    if match and (old.song_dir(match)/'lyrics.txt').is_file():
        ref=old.song_dir(match)
        for name in ('lyrics.txt','lyrics_sections.txt'):
            shutil.copyfile(ref/(name if (ref/name).is_file() else 'lyrics.txt'),d/name)
        (d/'lyrics_source').write_text('reused-local-reference; timing and translation regenerated from this performance')
        write_json(d/'lyrics_reference_reuse.json',{'source':str(ref/'lyrics.txt')})
        if resolved(ref):save_title(d,{'title':item['title'],'title_zh':resolved(ref),'artist_zh':item['artist_zh'],'reason':'同曲译名复用'})
    else:
        locator.lyrics(dict(item,artist='Heart' if item['title']=='Barracuda' else item['artist']),d)
    if (d/'lyrics_source').read_text().startswith('source-asr'):
        raise ValueError('参考歌词缺失，保留实际ASR待审核，不强套歌词')


def ensure_audio(c,item,remote):
    import soundfile as sf
    d=c.song_dir(item);audio=d/'audio.flac';vocals=d/'vocals.wav'
    if not audio.is_file():
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(d/'vertical/original-selected.mp4'),
                        '-vn','-ac','2','-ar','48000','-c:a','flac',str(d/'audio.pending.flac')],check=True)
        (d/'audio.pending.flac').replace(audio)
    if vocals.is_file():return
    if not remote:
        with PRIMARY:
            subprocess.run([str(SEP_PY),str(ROOT/'workflow/separate_roformer.py'),str(audio),'-o',str(vocals),'--device','mps'],check=True)
    else:
        job=REMOTE+'/jobs/'+c.slug+'--'+item['name']
        subprocess.run([*SSH,'mkdir -p '+shlex.quote(job)],check=True)
        transport=shlex.join(SSH[:-1])
        subprocess.run(['rsync','-a','--partial','-e',transport,str(audio),'zhaojing@192.168.3.10:'+job+'/audio.flac'],check=True)
        args=[REMOTE+'/venv/bin/python',REMOTE+'/workflow/separate_roformer.py',job+'/audio.flac','-o',job+'/vocals.wav','--device','mps']
        with (BASE/(c.slug+'--'+item['name']+'--remote-separation.log')).open('a') as log:
            subprocess.run([*SSH,'export PATH=/opt/homebrew/bin:$PATH; '+shlex.join(args)],check=True,stdout=log,stderr=subprocess.STDOUT)
        temporary=d/'vocals.remote.pending.wav'
        subprocess.run(['rsync','-a','--partial','-e',transport,'zhaojing@192.168.3.10:'+job+'/vocals.wav',str(temporary)],check=True)
        if abs(sf.info(str(audio)).duration-sf.info(str(temporary)).duration)>.3:raise ValueError('副机人声时长不符')
        temporary.replace(vocals)


def cover(c,item,remote):
    if reviewed_revision(c.song_dir(item)/'covers/ai'):return 'released'
    for attempt in range(2):
        checkpoint()
        plan=read_json(c.dir/'fibo-cover-plan.json',{})
        if item['name'] not in plan or attempt:reselect(c,item)
        plan=read_json(c.dir/'fibo-cover-plan.json')[item['name']]
        def infer():
            return generate_one(c,item,plan,ROOT/'work/fibo-batch'/c.slug,
                                Path('/Users/gold/Library/Caches/adele/fibo2-edit-turbo-q4'),
                                worker=BASE/'remote-fibo.json' if remote else None)
        if remote:result=infer()
        else:
            with PRIMARY:result=infer()
        stage=Path(result['stage']);record=visual_review(stage);key=c.slug+'/'+item['name']
        with STATE:
            rows=read_json(BASE/'visual-review.json',{});rows[key]=record;write_json(BASE/'visual-review.json',rows)
        if record['status']=='approved':
            publish(stage,record['review_hash'])
            try:verify_release(stage,c.slug,'http://127.0.0.1:8160')
            except (OSError,ValueError) as error:
                state(c.slug,item['name'],cover_status='published_pending_page_verification',cover_error=str(error));return 'published_pending_page_verification'
            return 'released_verified'
    return 'visual_review_rejected'


def one(job):
    c,folder,info=initialize(job);remote=job['executor']!='local'
    with (folder/'worker.lock').open('a') as own:
        fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state(c.slug,status='running',stage='source_location',executor=job['executor'])
        rows=transcript(job,folder,info['duration']);spans=locator.locate(job,rows,folder)
        hits={x['idx']:x for x in spans};segments=read_json(c.segments,{'items':[],'gaps':[]})
        segments['items']=[dict(it,start=hits[it['idx']]['start'],end=hits[it['idx']]['end'],review='pending',flags=['实际原片初定位，首尾待审核']) for it in c.song_items() if it['idx'] in hits]
        write_json(c.segments,segments)
        source_policy=read_json(c.dir/'vertical_source.json',{'source':job['source'],'songs':{}})
        for item in c.song_items():
            checkpoint();name=item['name'];d=c.song_dir(item);started=time.monotonic()
            previous=read_json(BASE/'status.json',{}).get(c.slug+'/'+name,{})
            if previous.get('stage')=='prepared' and previous.get('cover_status') in ('released','released_verified','published_pending_page_verification'):
                continue
            if item['idx'] not in hits:
                state(c.slug,name,status='needs_location_review',stage='location',note='参考歌单曲目未在当前原片中定位，不伪造片段');continue
            try:
                hit=hits[item['idx']];a,b=hit['start'],hit['end']
                write_json(d/'song.json',dict(item,slice=[a,b],preview=[a,b],source_file=job['source'],source_kind='original',lang='en'))
                directory=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews')/c.slug/'browser-sources'/name
                source_policy['songs'][name]={'source':job['source'],'kind':'original','slice':[a,b],'directory':str(directory)}
                write_json(c.dir/'vertical_source.json',source_policy)
                state(c.slug,name,status='running',stage='preview_and_reference',executor=job['executor'])
                references(c,item)
                with PREVIEW:enable_browser(c,item)
                state(c.slug,name,status='running',stage='vocal_separation')
                ensure_audio(c,item,remote)
                state(c.slug,name,status='running',stage='asr_alignment_translation')
                if subtitle_audit(c,item)['status']=='missing':
                    with ALIGNMENT,(BASE/(c.slug+'--'+name+'.log')).open('a') as log:
                        subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,name],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
                state(c.slug,name,status='running',stage='posting_information')
                draft_meta(c,item,{'start':a,'end':b},SimpleNamespace(force=False))
                meta=prepare_metadata(c,item);sub=subtitle_audit(c,item)
                with STATE:
                    catalog=read_json(c.setlist)
                    for row in catalog['items']:
                        if row['name']==name:row['review_hidden']=False
                    write_json(c.setlist,catalog)
                state(c.slug,name,status='running',stage='standard_fibo_cover',metadata=meta,subtitles=sub)
                cover_status=cover(c,item,remote)
                write_bundle(c,item)
                state(c.slug,name,status='needs_human_review',stage='prepared',cover_status=cover_status,
                      elapsed_seconds=round(time.monotonic()-started,3),human_approved=False)
            except Exception as error:
                state(c.slug,name,status='needs_repair',error=str(error));traceback.print_exc()
        state(c.slug,status='pass_complete_review_pending',stage='done')


if __name__=='__main__':
    with (BASE/'pipeline.lock').open('a') as own:
        fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        (BASE/'pid').write_text(str(os.getpid()))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(one,job) for job in read_json(BASE/'jobs.json')]
            for future in futures:future.result()
