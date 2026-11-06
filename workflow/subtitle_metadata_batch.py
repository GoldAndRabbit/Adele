"""Prioritize all visible subtitles and posting copy; no AI images or final exports."""
import argparse
import fcntl
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

import pysubs2
from workflow.live.paths import ROOT,VENV_PY,SEP_PY,read_json,write_json
from workflow.preview_batch import visible,metadata,enable_browser

BASE=ROOT/'work/subtitle-metadata-library'


def subtitle_audit(c,it):
    d=c.song_dir(it)
    file=next((d/'subs'/n for n in ['lyrics_poetic.ass','lyrics_literal.ass','lyrics.ass'] if (d/'subs'/n).is_file()),None)
    if not file:return {'status':'missing','issues':['缺少双语字幕']}
    try:
        events=[e for e in pysubs2.load(file) if not e.is_comment and e.plaintext.strip()]
    except Exception as e:return {'status':'invalid','issues':[str(e)]}
    issues=[]
    if not events:issues.append('字幕为空')
    if not any(re.search('[\u3400-\u9fff]',e.plaintext) for e in events):issues.append('没有中文字幕')
    if any(e.start<0 or e.end<=e.start for e in events):issues.append('非法时间范围')
    info=read_json(d/'song.json',{})
    selection=read_json(c.dir/'vertical_source.json',{}).get('songs',{}).get(it['name'])
    span=(selection or {}).get('slice') or info.get('slice')
    if span and any(e.end>(span[1]-span[0]+1)*1000 for e in events):issues.append('字幕超出所选片段尾部')
    lines=read_json(d/'subs/lines.json',[])
    unresolved=sum(not r.get('removed') and r.get('verdict') in ['warn','bad'] for r in lines)
    return {'status':'needs_review' if issues else 'structurally_valid','issues':issues,'file':str(file),'events':len(events),'unresolved_alignment_rows':unresolved,'human_approved':False}


def prepare_metadata(c,it):
    d=c.song_dir(it);info=c.load('info') or {};draft=read_json(d/'post_draft.json',{})
    if not draft:
        # Facts only: never invent long introductions, chart history, or aliases.
        draft={'song':{'title':it['title'],'artist':it.get('artist') or info.get('artist'),'artist_zh':info.get('artist_zh')},
               'performance':{'event':info.get('title_zh') or info.get('title'),'event_en':info.get('title_en') or info.get('title_en_short'),'date':info.get('date')},
               'metadata_origin':'existing concert and setlist facts','intro':{},'tags':[]}
        write_json(d/'post_draft.json',draft)
    from workflow.song.title_translation import resolved,save
    title=resolved(d) or (draft.get('song') or {}).get('title_zh')
    if not title:
        existing=read_json(d/'subs/translation/result.json',{})
        match=re.search(r'《([^》]+)》',existing.get('title_zh',''))
        if match and re.search('[\u3400-\u9fff]',match[1]):
            title=match[1];save(d,{'title':it['title'],'title_zh':title,'artist_zh':draft['song'].get('artist_zh'),'reason':'复用已有字幕译名，不重新翻译'})
    if title:
        draft['song']['title_zh']=title
        write_json(d/'post_draft.json',draft)
    metadata(c,it)
    bundle=read_json(d/'delivery_bundle.json');post=bundle['douyin'];issues=[]
    if not post or not post.get('title'):issues.append('抖音标题为空')
    if post.get('title_chars',0)>30:issues.append('抖音标题超长')
    if post.get('description_chars',0)>1000:issues.append('抖音描述超长')
    if not post.get('description','').startswith('#'):issues.append('抖音描述不是话题格式')
    if '不允许保存' not in post.get('publish_settings',''):issues.append('保存权限不符')
    if bundle['bilibili']['needs_title_shortening']:issues.append('B站标题超过80字符，保留全文待缩句')
    if not title:issues.append('中文歌名待确认')
    return {'status':'needs_review' if issues else 'ready','issues':issues,'douyin_title':post.get('title'),'bilibili_title_chars':bundle['bilibili']['title_characters']}


def save_status(c,it,**changes):
    target=BASE/f'{c.slug}--{it["name"]}.json'
    row=read_json(target,{'concert':c.slug,'song':it['name'],'title':it['title'],'link':f'http://127.0.0.1:8160/#/{c.slug}/{it["name"]}'})
    row.update(changes,updated=datetime.now().isoformat());write_json(target,row)


def run_metadata():
    for c,it in visible():
        if (BASE/'PAUSED').exists():break
        try:
            sub=subtitle_audit(c,it);meta=prepare_metadata(c,it)
            save_status(c,it,subtitles=sub,metadata=meta,status='needs_subtitles' if sub['status']=='missing' else 'needs_review' if sub['issues'] or meta['issues'] else 'ready_for_review')
        except Exception as e:save_status(c,it,status='failed',error=str(e));print('METADATA_FAILED',c.slug,it['name'],str(e),flush=True)
    summary()


def ensure_audio(c,it):
    d=c.song_dir(it);enable_browser(c,it)
    clip=d/'vertical/original-selected.mp4'
    if not (d/'audio.flac').is_file():
        pending=d/'audio.pending.flac'
        subprocess.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y','-i',str(clip),'-vn','-ac','2','-ar','48000','-c:a','flac',str(pending)],check=True)
        pending.replace(d/'audio.flac')
    if not (d/'vocals.wav').is_file():
        pending=d/'vocals.pending.wav'
        subprocess.run([str(SEP_PY),str(ROOT/'workflow/separate_roformer.py'),str(d/'audio.flac'),'-o',str(pending)],check=True)
        pending.replace(d/'vocals.wav')


def run_subtitles():
    for c,it in visible():
        if (BASE/'PAUSED').exists():break
        if subtitle_audit(c,it)['status']!='missing':continue
        d=c.song_dir(it)
        try:
            save_status(c,it,status='running_subtitles',stage='audio')
            if not (d/'lyrics.txt').is_file():raise ValueError('缺少参考歌词，不能盲目识别')
            ensure_audio(c,it)
            save_status(c,it,status='running_subtitles',stage='asr_alignment_translation')
            log=BASE/f'{c.slug}--{it["name"]}.log'
            with log.open('a') as output:
                subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,it['name']],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True)
            sub=subtitle_audit(c,it);meta=prepare_metadata(c,it)
            save_status(c,it,subtitles=sub,metadata=meta,status='needs_review' if sub['issues'] or meta['issues'] else 'ready_for_review',stage='done')
            print('SUBTITLES_READY',c.slug,it['name'],flush=True)
        except Exception as e:
            save_status(c,it,status='failed',error=str(e));print('SUBTITLES_FAILED',c.slug,it['name'],str(e),flush=True)
        summary()


def summary():
    rows=[read_json(p) for p in BASE.glob('*--*.json')]
    result={'at':datetime.now().isoformat(),'total':len(rows),'status':dict(Counter(r.get('status') for r in rows)),
        'subtitle_status':dict(Counter(r.get('subtitles',{}).get('status','unknown') for r in rows)),
        'metadata_status':dict(Counter(r.get('metadata',{}).get('status','unknown') for r in rows))}
    write_json(BASE/'summary.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--subtitles',action='store_true');args=parser.parse_args()
    BASE.mkdir(parents=True,exist_ok=True)
    with (BASE/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run_metadata()
        if args.subtitles:run_subtitles()
        summary()
