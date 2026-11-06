"""Resumable visible-library browser previews + at most one new AI master per song.

No final rendering, interpolation, cover adoption, or publishing is called here.
Run --inventory first; --run processes eligible items sequentially.
"""
import argparse
import fcntl
import hashlib
import os
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

from workflow.live.paths import ROOT, CONCERTS, Concert, read_json, write_json
from workflow.vertical_cover import original_source, cover_ffmpeg

BASE = ROOT / 'work/preview-ai-library'


def visible():
    for folder in sorted(CONCERTS.iterdir()):
        if folder.is_dir():
            concert = Concert(folder.name)
            for item in concert.song_items():
                if not item.get('review_hidden'):
                    yield concert, item


def inventory():
    rows = []
    for c, it in visible():
        d = c.song_dir(it)
        try:
            source = str(original_source(c, it))
        except (FileNotFoundError, KeyError):
            source = None
        captions = any((d/'subs'/n).is_file() for n in ['lyrics_poetic.ass','lyrics_literal.ass','lyrics.ass'])
        ai = d/'covers/ai'
        masters = [m for m in read_json(ai/'masters.json', []) if (ai/m['file']).is_file()]
        prior = list(ai.glob('runs/*/candidate-*.json'))
        rows.append(dict(concert=c.slug, song=it['name'], title=it['title'], source=source,
            subtitles=captions, ai_masters=len(masters), ai_prior_attempts=len(prior),
            browser=(d/'vertical/original-selected.mp4').is_file(),
            status='missing_source' if not source else 'missing_subtitles' if not captions else 'queued',
            link=f'http://127.0.0.1:8160/#/{c.slug}/{it["name"]}'))
    return rows


def enable_browser(c, it):
    """Keep authoritative source choices and reuse their prepared clean clips."""
    from workflow.browser_library import prepare_browser
    d = c.song_dir(it)
    policy = read_json(c.dir/'vertical_source.json', {})
    selected = policy.get('songs', {}).get(it['name'])
    if selected:
        source = original_source(c,it)
        output = Path(selected['directory'])/'source.mp4'
        expected = dict(source=str(source), mtime=source.stat().st_mtime_ns, slice=selected['slice'])
        if not output.is_file() or read_json(output.parent/'source.json') != expected:
            prepare_browser(c,it)
        from workflow.vertical_source import _publish
        _publish(c,it,output)
        info = read_json(d/'song.json', {})
        info['preview_mode'] = 'browser'
        write_json(d/'song.json',info)
        config = read_json(c.dir/'browser_previews.json', {'songs':[]})
        config['songs'] = list(dict.fromkeys([*config['songs'],it['name']]))
        write_json(c.dir/'browser_previews.json',config)
    else:
        prepare_browser(c,it)
    from workflow.portrait_browser import preview_data
    preview_data(c,it,d)  # validate title data without burning a video


def one_cover(c,it):
    from workflow.seedream_cover import generate_trial
    from workflow.cover_frames import candidate_frames
    from workflow.cover_pool_quality import assess
    ai=c.song_dir(it)/'covers/ai'
    masters=[m for m in read_json(ai/'masters.json',[]) if (ai/m['file']).is_file()]
    if masters:
        return 'reused'
    records=list(ai.glob('runs/*/candidate-*.json'))
    if records:
        return 'prior_attempt_needs_review'
    source=original_source(c,it)
    policy=read_json(c.dir/'vertical_source.json',{}).get('songs',{}).get(it['name'])
    span=(policy or {}).get('slice') or read_json(c.song_dir(it)/'song.json',{}).get('slice')
    if not span: raise ValueError('缺少已确认的原片范围')
    rows=[r for r in candidate_frames(c,it) if r.get('path') and Path(r['path']).is_file()]
    if not c.has_cover_pool:
        rows=[r for r in rows if span[0]<=r['t']<span[1]]
    if not rows:
        rows=[{'t':span[0]+offset} for offset in range(6,max(7,int(span[1]-span[0])-2),6)]
    # Spread across the original-frame pool. Re-extract to avoid stale-source JPEGs.
    chosen_rows=[rows[round(i*(len(rows)-1)/min(23,len(rows)-1))] for i in range(min(24,len(rows)))] if len(rows)>1 else rows
    references=ai/'references';references.mkdir(parents=True,exist_ok=True)
    accepted=[]
    for start in range(0,len(chosen_rows),8):
        batch=[];by_name={}
        for row in chosen_rows[start:start+8]:
            p=references/f'library-{row["t"]:.3f}.jpg'
            subprocess.run([cover_ffmpeg(),'-nostdin','-v','error','-y','-ss',str(row['t']),'-i',str(source),'-frames:v','1','-vf','scale=1280:-2','-q:v','2',str(p)],check=True,stderr=subprocess.PIPE)
            batch.append((p,hashlib.sha256(p.read_bytes()).hexdigest()));by_name[p.name]=row
        report=assess(batch)
        write_json(references/f'quality-{start}.json',report)
        accepted.extend((float(v.get('detail',{}).get('score',0)), references/k, by_name[k], v) for k,v in report.items() if v['approved'])
    if not accepted: return 'needs_qualified_reference'
    _,reference,row,quality=max(accepted,key=lambda x:x[0])
    plan=ai/'library-plan.json'
    write_json(plan,dict(strategy='library-one-master-v1',source=str(source),source_range=span,candidates=[dict(
        label='AI 封面', reference=str(reference.resolve()),source_time=row['t'],
        selection_reason=quality['reason'],reference_role='original performance frame',
        prompt='Create a premium painterly concert cover illustration based on this original performance frame. Preserve the recognizable performer, pose, clothing and actual stage palette. Elegant detailed oil-paint texture, natural anatomy, centered clear face and upper body, enough surrounding space for both portrait 3:4 and landscape 4:3 crops. No text, letters, logos, watermarks or borders. Do not invent additional people.')]))
    generate_trial(c,it,plan)
    return 'generated'


def run(concert_filter=None, wait=False):
    BASE.mkdir(parents=True,exist_ok=True)
    with (BASE/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX if wait else fcntl.LOCK_EX|fcntl.LOCK_NB)
        rows=inventory();write_json(BASE/'inventory.json',rows)
        for row in rows:
            if concert_filter and row['concert'] != concert_filter:continue
            if (BASE/'PAUSED').exists(): break
            c=Concert(row['concert']);it=c.item(row['song'])
            target=BASE/f'{c.slug}--{it["name"]}.json'
            if read_json(target,{}).get('status')=='ready':continue
            if row['status']!='queued':write_json(target,row);continue
            row.update(status='running',started=datetime.now().isoformat());write_json(target,row)
            errors={}
            for stage, action in [('preview',lambda:enable_browser(c,it)),('metadata',lambda:metadata(c,it)),('ai',lambda:one_cover(c,it))]:
                if (BASE/'PAUSED').exists():break
                row['stage']=stage;write_json(target,row)
                try:row[stage+'_result']=action() or 'ready'
                except (Exception,SystemExit) as e:errors[stage]=str(e)[:500]
                write_json(target,row)
            if row.get('metadata_result')=='ready':
                from workflow.delivery_bundle import write_bundle
                write_bundle(c,it)
            row.update(errors=errors,status='failed' if errors else 'ready' if row.get('ai_result') in ('reused','generated') else 'needs_review',finished=datetime.now().isoformat())
            write_json(target,row);print(row['status'],c.slug,it['name'],flush=True)


def metadata(c,it):
    from workflow.delivery_bundle import write_bundle
    from workflow.vertical_post import posting_inputs, submission, cover_attachment
    d=c.song_dir(it);draft=read_json(d/'post_draft.json',{})
    if not draft:raise ValueError('缺少投稿基础资料，不编造标题信息')
    post=submission(*posting_inputs(c,it,draft))
    selection=read_json(d/'vertical/selected.json',{})
    post['cover']=cover_attachment(d,selection.get('cover'))
    (d/'vertical').mkdir(exist_ok=True)
    write_json(d/'vertical/douyin_submission.json',post)
    write_bundle(c,it)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--inventory',action='store_true')
    parser.add_argument('--concert',help='Only process this concert, preserving the full inventory')
    parser.add_argument('--wait',action='store_true',help='Wait for the current library worker to finish')
    args=parser.parse_args()
    if args.run:run(args.concert,args.wait)
    else:
        BASE.mkdir(parents=True,exist_ok=True)
        rows=inventory();write_json(BASE/'inventory.json',rows)
        print(dict(total=len(rows),statuses=dict(Counter(r['status'] for r in rows)),existing_ai=sum(r['ai_masters']>0 for r in rows),existing_clips=sum(r['browser'] for r in rows)))
