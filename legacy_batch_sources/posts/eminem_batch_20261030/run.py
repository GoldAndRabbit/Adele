"""本次任务队列：只生成审核素材；不会调用 render / hd / upload。"""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor

ROOT = Path('/Users/gold/repos/adele')
sys.path[:0] = [str(ROOT), str(ROOT/'workflow')]
from workflow.live.paths import Concert, write_json
from workflow.live.lyrics import fetch_part
from workflow.llm import load_env
import requests

B = ROOT/'posts/eminem_batch_20261030'
PYTHON = ROOT/'.venv/bin/python'
M = json.loads((B/'manifest.json').read_text())
STATE = json.loads((B/'status.json').read_text()) if (B/'status.json').exists() else {'jobs':{}, 'started_at':datetime.datetime.now().isoformat()}
STATE['pid'] = os.getpid()
STATE['supervisor_pid'] = os.getpid()
STATE.pop('finished_at', None)
STATE_LOCK = threading.Lock()

def state(name, stage, status, **kw):
    with STATE_LOCK:
        stages = STATE['jobs'].get(name, {}).get('stages', {})
        stages[stage] = status
        STATE['jobs'][name] = {'stage':stage,'status':status,'at':datetime.datetime.now().isoformat(),
                               'stages':stages, 'active_stages':[s for s,v in stages.items() if v=='running'], **kw}
        write_json(B/'status.json', STATE)
        print(name, stage, status, kw, flush=True)

def room():
    free = shutil.disk_usage(ROOT).free
    if free < 5*1024**3:
        raise RuntimeError(f'磁盘剩余 {free/1024**3:.1f}GiB，低于5GiB预留；保留已有结果，等待清理后重跑')

def cmd(name, stage, args):
    room()
    state(name,stage,'running')
    logs=B/'logs';logs.mkdir(exist_ok=True)
    with (logs/f'{name}_{stage}.log').open('a') as log:
        log.write('\n'+datetime.datetime.now().isoformat()+' '+repr(list(map(str,args)))+'\n');log.flush()
        result=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError(f'{stage} exit={result.returncode}; log={logs/name}_{stage}.log')
    state(name,stage,'done')

def references(job):
    name=job['name'];d=ROOT/'posts'/name
    if (d/'lyrics.txt').exists() and (d/'lyrics_sections.txt').exists():return
    state(name,'lyrics','running')
    cache=B/'references';cache.mkdir(exist_ok=True)
    plain=[];sections=[];facts=[]
    with requests.Session() as s:
        s.headers['User-Agent']='Mozilla/5.0 (compatible; YouTubeLyrics/1.0)'
        for part in job['parts']:
            import hashlib
            key=hashlib.sha256((job['artist']+'|'+part).encode()).hexdigest()[:16]
            f=cache/f'{key}.json'
            if f.exists():r=json.loads(f.read_text())
            else:
                url,txt,sec,fact=fetch_part(s,part,job['artist'])
                r={'url':url,'text':txt,'sections':sec,'facts':fact};write_json(f,r)
            plain.append(r['text'].strip());sections.append(r['sections'].strip());facts.append(r['facts'])
    (d/'lyrics.txt').write_text('\n\n\n'.join(plain)+'\n')
    (d/'lyrics_sections.txt').write_text('\n\n\n'.join(sections)+'\n')
    write_json(d/'genius_facts.json',facts)
    state(name,'lyrics','done')

def singles():
    for j in M['singles']:
        n=j['name'];d=ROOT/'posts'/n
        if '--remaining-only' in sys.argv and STATE['jobs'].get(n, {}).get('stage') == 'review_ready':
            print(n, 'already ready; preserved, skipped', flush=True)
            continue
        try:
            references(j)
            cmd(n,'source',[PYTHON,B/'download.py','--name',n,'--url',j['url'],'--cookies-from-browser','chrome','--from','download','--to','download'])
            probe = json.loads((d/'download_probe.json').read_text()) if (d/'download_probe.json').exists() else {}
            official = ['--sub-lang','en'] if any(x.split('-')[0]=='en' for x in probe.get('subtitles', [])) else []
            if not (d/'audio.flac').exists() or not (d/'vocals.wav').exists():
                cmd(n,'separate',[PYTHON,'workflow/make_mv.py','--name',n,'--url',j['url'],'--cookies-from-browser','chrome','--song-title',j['parts'][0],'--artist',j['artist'],'--from','prep' if not (d/'audio.flac').exists() else 'separate','--to','separate',*official])
            def metadata():
                if not (d/'post'/f'{n}.json').exists():
                    cmd(n,'metadata',[PYTHON,'workflow/make_meta.py','--name',n,'--subtitle-langs','英语,中文','--note',j['note']+'\n歌名：'+' / '.join(j['parts'])+'；歌手：'+j['artist']+'。不能把上传日期当演出日期。'])
            def covers():
                cover_dir = d/'post/cover'
                layout = {'version':2,'artist_zh':'埃米纳姆','event':j.get('cover_event',''),'sub_fit':'natural'}
                stamp = cover_dir/'layout.json'
                if stamp.exists() and json.loads(stamp.read_text()) == layout:
                    return
                args = [PYTHON,'workflow/make_cover.py','--name',n,'--title',' / '.join(j['parts']),
                        '--subtitle','Eminem · 中英字幕','--artist-zh','埃米纳姆','--sub-fit','natural',
                        *(['--event',j['cover_event']] if j.get('cover_event') else []),
                        '--who','Eminem，白人男说唱歌手']
                if list(cover_dir.glob('frame_*.jpg')):
                    args.append('--recompose')
                cmd(n,'covers',args)
                write_json(stamp,layout)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(metadata), pool.submit(covers)]
                for future in futures:
                    future.result()
            if not (d/'subs/lyrics_poetic.ass').exists():
                cmd(n,'subtitles',[PYTHON,'-u','-m','workflow.song.run','post',n])
            if not (d/'watermark.json').exists():
                cmd(n,'watermark',[PYTHON,'-m','workflow.song.watermark','post',n])
            cmd(n,'review',[PYTHON,'-m','workflow.live.singles',n])
            state(n,'review_ready','done',needs_manual_review=True,metadata_qa_pending=True)
        except Exception as e:
            state(n,'failed','failed',error=str(e))

def concert():
    co=M['concert'];n=co['slug'];c=Concert(n)
    try:
        state(n,'download_wait','running')
        start=time.time()
        while not Path(json.loads(c.info.read_text())['source_file']).exists():
            if time.time()-start>3600:raise RuntimeError('整场下载超过1小时仍未完成，检查 concert_download.log 后重跑')
            room();time.sleep(15)
        state(n,'download_wait','done')
        cmd(n,'ingest',[PYTHON,'-u','-m','workflow.live','run',n,'--from','ingest','--to','ingest'])
        cmd(n,'lyrics',[PYTHON,'-u','-m','workflow.live','run',n,'--from','lyrics','--to','lyrics'])
        # 边界来自用户，保留 segments.json；不再跑 segment 覆盖给定时间点。
        cmd(n,'separate',[PYTHON,'-u','-m','workflow.live','run',n,'--from','separate','--to','separate'])
        for item in c.song_items():
            cmd(n,'refine_'+item['name'],[PYTHON,'-u','-m','workflow.live','run',n,'--from','refine','--to','refine','--songs',str(item['idx'])])
            cmd(n,'package_'+item['name'],[PYTHON,'-u','-m','workflow.live','run',n,'--from','package','--to','package','--songs',str(item['idx'])])
        missing=[]
        for item in c.song_items():
            d=c.song_dir(item)
            if not (d/'subs/lyrics_poetic.ass').exists() or not (d/'post_draft.json').exists() or not (d/'preview.mp4').exists():missing.append(item['name'])
            elif not (d/'watermark.json').exists():
                cmd(item['name'],'watermark',[PYTHON,'-m','workflow.song.watermark','song',n,item['name']])
        state(n,'review_materials','partial' if missing else 'done',missing=missing,needs_manual_review=True)
    except Exception as e:state(n,'failed','failed',error=str(e))

if __name__=='__main__':
    load_env()
    # 演唱会优先，按用户给定时间点逐首做到可审核，然后补剩余单曲。
    if '--references-only' in sys.argv:
        for j in M['singles']:
            try:references(j)
            except Exception as e:state(j['name'],'lyrics','failed',error=str(e))
    else:
        concert()
        singles()
        STATE['finished_at']=datetime.datetime.now().isoformat()
        write_json(B/'status.json',STATE)
        print('审核素材队列结束；查看 status.json。未渲染、未投稿。',flush=True)
