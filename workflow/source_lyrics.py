"""Recognize original concert audio independently of song cuts and lyric alignment.

python -m workflow.source_lyrics CONCERT

55-second overlapping chunks are cached by original and audio-track identity.
Every result keeps its coverage, including silence. Failed chunks never produce
a successful content-check certificate. No reference lyrics are sent to ASR.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from workflow.content_check import EVIDENCE, boundary_identity, digest, selection, source_identity
from workflow.live.paths import Concert, ROOT, read_json, write_json

def cached_sentence(path):
    """A malformed old cache is not silence and cannot poison a fresh retry."""
    try:
        cache=read_json(path,{})
        if not isinstance(cache,dict) or len(cache)!=1:return None
        sentence=next(iter(cache.values()))['output']['output']['sentence']
        return sentence if isinstance(sentence,dict) and isinstance(sentence.get('words'),list) else None
    except (json.JSONDecodeError,KeyError,TypeError,AttributeError):return None


def saved_vocal_reads(concert, item, original):
    """Reuse independent vocal ASR with its original source clock, not lyric fits.

    Extending a cut moves old isolated audio/caches into a backup. Those reads
    still describe the same original bytes; their old offset must be retained.
    A missing/different original binding or isolated-audio duration is rejected.
    """
    import soundfile as sf
    from workflow.content_check import file_hash
    d=concert.song_dir(item);folders=[d]
    folders.extend(sorted((d/'reports').glob('before_cut_repair_*')))
    rows=[];seen=set()
    for folder in folders:
        info=read_json(folder/'song.json',{})
        span=read_json(folder/'old-slice.json',info.get('slice'))
        source=info.get('source_file')
        if not source or not span or Path(source).resolve()!=Path(original['path']):continue
        recorded=read_json(folder/'reports/content_check.json',{}).get('input',{}).get('source')
        if recorded is not None and recorded!=original:continue
        vocal=folder/'vocals.wav'
        if not vocal.is_file():continue
        if abs(sf.info(vocal).duration-(span[1]-span[0]))>.3:continue
        for p in sorted((folder/'subs').glob('asr_words_*.json')):
            ws=read_json(p)
            if not isinstance(ws,list) or not ws:continue
            if any(not {'s','e','w'}<=set(w) or not -.2<=w['s']<=w['e']<=span[1]-span[0]+.5 for w in ws):continue
            cache_sha=file_hash(p);identity=(cache_sha,tuple(span))
            if identity in seen:continue
            seen.add(identity)
            rows.append({'origin':'independent_saved_vocal_asr','original_source':original,
                'source_range':span,'cache':str(p.resolve()),'cache_sha256':cache_sha,
                'audio_track':source_identity(vocal),
                'words':[dict(w,s=w['s']+span[0],e=w['e']+span[0]) for w in ws]})
    return rows


def capture(concert, *, workers=5, items=None):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    from dotenv import load_dotenv
    sys.path.insert(0, str(ROOT/'workflow'))
    from workflow.live.asr_match import asr_words, decode_sentence, MODEL
    load_dotenv(ROOT/'.env')
    items = items if items is not None else concert.song_items()
    sources = {}
    for item in items:
        policy = selection(concert, item)
        source = Path(policy['source']).resolve()
        sources.setdefault(source, []).append(item)
    summary = []
    for source, source_items in sources.items():
        original = source_identity(source)
        meta = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(source)]))
        duration = float(meta['format']['duration'])
        audio_binding = read_json(concert.dir/'reports/source_audio.json', {})
        vocal = concert.vocals if (concert.vocals.is_file() and audio_binding.get('source') == original) else None
        track = source_identity(vocal) if vocal else original
        recipe = 'source_clock_async1_v2' if vocal is None and source.suffix.lower()=='.ts' else None
        bank_key={'source':original,'track':track,'model':MODEL}
        if recipe:bank_key['audio_recipe']=recipe
        prior_bank=concert.dir/'reports/source-asr'/digest(bank_key)[:24]
        bank_key['word_time_recipe']='raw_sung_onsets_v2'
        bank = concert.dir/'reports/source-asr'/digest(bank_key)[:24]
        bank.mkdir(parents=True, exist_ok=True)
        with (bank/'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            clock_audio=None
            if recipe:
                from workflow.content_audio_review import cached_audio
                clock_audio=cached_audio(source)
            spans = [(float(a), min(float(a+55),duration)) for a in range(0,int(duration)+1,50)
                     if a < duration-.2]
            cached_starts={a for a,b in spans if read_json(bank/f'{a:07.1f}.json',{}).get('status')=='ok'}
            # All source is covered. It catches songs mistakenly left entirely in gaps.
            def one(span):
                a,b = span
                path = bank/f'{a:07.1f}.json'
                cached = read_json(path, {})
                if cached.get('status') == 'ok':
                    return cached
                try:
                    raw_path=prior_bank/f'{a:07.1f}.cache.json'
                    sentence=cached_sentence(raw_path)
                    if sentence is not None:
                        ws=decode_sentence(sentence,a,clamp_long_words=False)
                        origin='raw_asr_cache'
                    else:
                        if vocal or clock_audio:
                            with sf.SoundFile(vocal or clock_audio) as handle:
                                sr = handle.samplerate
                                handle.seek(round(a*sr))
                                y = handle.read(round((b-a)*sr),dtype='float32',always_2d=True).mean(axis=1)
                            common=gcd(sr,16000)
                            y=resample_poly(y,16000//common,sr//common)
                        else:
                            raw=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-ss',str(a),
                                '-i',str(source),'-t',str(b-a),'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'])
                            y=np.frombuffer(raw,dtype='<f4')
                        ws=asr_words(y,16000,os.environ['ALIYUN_BAILIAN_API_KEY'],bank/f'{a:07.1f}.cache.json',t0=a,
                                     request_timeout=60,attempts=2,clamp_long_words=False)
                        origin='original_asr'
                    ws=[{k:w[k] for k in ('w','s','e','punct')} for w in ws
                        if a-.1 <= w['s'] < b and w['e'] >= w['s']]
                    for w in ws:w['e']=min(w['e'],b)
                    result={'start':a,'end':b,'status':'ok','words':ws,'evidence_source':origin}
                except Exception as exc:
                    result={'start':a,'end':b,'status':'failed','error':str(exc),'words':[]}
                write_json(path,result)
                return result
            results=[]
            with ThreadPoolExecutor(max_workers=workers) as pool:
                jobs=[pool.submit(one,s) for s in spans]
                for job in as_completed(jobs):
                    result=job.result();results.append(result)
                    mode=('复用证据缓存' if result['start'] in cached_starts else
                          '复用原始识别长音起点' if result.get('evidence_source')=='raw_asr_cache' else '新识别')
                    print(f'原片证据 {len(results)}/{len(spans)} {result["start"]:.0f}–{result["end"]:.0f}s {mode} {result["status"]}',flush=True)
            results.sort(key=lambda r:r['start'])
            combined=[]
            for i,r in enumerate(results):
                left=r['start']+(2.5 if i else 0)
                right=r['end']-(2.5 if i<len(results)-1 else 0)
                combined.extend(w for w in r['words'] if left<=w['s']<right)
            combined.sort(key=lambda w:w['s'])
            for refined in sorted((bank/'refinements').glob('*.json'),
                                  key=lambda p:read_json(p)['end']-read_json(p)['start'],reverse=True):
                r=read_json(refined)
                if r.get('status')=='ok' and r.get('words'):
                    combined=[w for w in combined if not r['start']<=w['s']<r['end']]+r['words']
            combined.sort(key=lambda w:w['s'])
            transcript={'source':original,'audio_track':track,'source_duration':duration,
                'model':MODEL,'contexts':[{k:v for k,v in r.items() if k!='words'} for r in results],
                'words':combined,'word_time_recipe':'raw_sung_onsets_v2'}
            if recipe:transcript['audio_recipe']=recipe
            write_json(bank/'transcript.json',transcript)
            alternates=[]
            for path in (concert.dir/'reports/source-asr').glob('*/transcript.json'):
                if path.parent==bank:
                    continue
                other=read_json(path)
                if (other.get('source')==original and (not recipe or other.get('audio_recipe')==recipe)
                        and other.get('word_time_recipe')=='raw_sung_onsets_v2'):
                    alternates.append(other)
                    for p in (path.parent/'refinements').glob('*.json'):
                        r=read_json(p)
                        if r.get('status')=='ok' and r.get('words'):
                            alternates.append({'source':original,'audio_track':other['audio_track'],
                                               'model':MODEL,'words':r['words']})
            for item in source_items:
                a,b=selection(concert,item)['slice'];lo,hi=max(0,a-35),min(duration,b+35)
                evidence={'input':boundary_identity(concert,item),'source_duration':duration,
                    'model':MODEL,'bank':str(bank.resolve()),'audio_track':track,
                    'contexts':[r for r in transcript['contexts'] if r['end']>=lo and r['start']<=hi],
                    'words':[w for w in combined if lo<=w['s']<=hi],
                    'alternate_reads':[{'audio_track':r['audio_track'],'model':r['model'],
                        'words':[w for w in r['words'] if lo<=w['s']<=hi]} for r in alternates
                        if any(lo<=w['s']<=hi for w in r['words'])]}
                evidence['alternate_reads'].extend(saved_vocal_reads(concert,item,original))
                path=concert.song_dir(item)/EVIDENCE;path.parent.mkdir(exist_ok=True)
                write_json(path,evidence)
            summary.append({'source':str(source),'chunks':len(results),
                            'failed':sum(r['status']!='ok' for r in results),'bank':str(bank.resolve())})
    return summary


def refine(concert, intervals, *, workers=3, track='vocals'):
    """Re-recognize difficult original-vocal windows without sending any lyrics."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    from dotenv import load_dotenv
    sys.path.insert(0,str(ROOT/'workflow'))
    from workflow.live.asr_match import asr_words, MODEL
    load_dotenv(ROOT/'.env')
    original=source_identity(selection(concert,concert.song_items()[0])['source'])
    binding=read_json(concert.dir/'reports/source_audio.json',{})
    if binding.get('source')!=original or not concert.vocals.is_file():
        raise ValueError('短窗复核需要与原片绑定的完整人声')
    audio_path=concert.vocals if track=='vocals' else concert.audio
    track_identity=source_identity(audio_path) if track=='vocals' else original
    bank=concert.dir/'reports/source-asr'/digest({'source':original,'track':track_identity,'model':MODEL})[:24]
    dest=bank/'refinements';dest.mkdir(parents=True,exist_ok=True)
    def one(span):
        a,b=span;path=dest/f'{a:.2f}-{b:.2f}.json'
        if read_json(path,{}).get('status')=='ok':return read_json(path)
        with sf.SoundFile(audio_path) as h:
            sr=h.samplerate;h.seek(round(a*sr));y=h.read(round((b-a)*sr),dtype='float32',always_2d=True).mean(1)
        common=gcd(sr,16000);y=resample_poly(y,16000//common,sr//common)
        ws=asr_words(y,16000,os.environ['ALIYUN_BAILIAN_API_KEY'],dest/f'{a:.2f}-{b:.2f}.cache',t0=a)
        ws=[{k:w[k] for k in ('w','s','e','punct')} for w in ws if a<=w['s']<b]
        for w in ws:w['e']=min(b,w['e'])
        result={'start':a,'end':b,'status':'ok','words':ws};write_json(path,result);return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results=list(pool.map(one,intervals))
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('concert');p.add_argument('--workers',type=int,default=5)
    a=p.parse_args();result=capture(Concert(a.concert),workers=a.workers)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if any(r['failed'] for r in result):raise SystemExit(1)


if __name__=='__main__':main()
