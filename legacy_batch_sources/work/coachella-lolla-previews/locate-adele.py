from common import *
import pysubs2
job=next(j for j in read_json(BASE/'jobs.json') if j['slug']=='adele_one_night_only_2021')
folder=BASE/job['slug'];rows=read_json(folder/'transcript.json')
spans=base.locate(job,rows,folder)
print('LOCATIONS',spans,flush=True)
# The sidecar has source-owned, non-rolling lyric cue timestamps.
sub=pysubs2.load(str(folder/'captions.srt'));music=[e for e in sub if '♪' in e.plaintext or '♫' in e.plaintext]
for s in spans:
 inside=[e for e in music if e.end/1000>s['start'] and e.start/1000<s['end']]
 if not inside:raise ValueError(f'No source lyric captions for {s}')
 s['start']=round(max(0,min(e.start for e in inside)/1000-2),3)
 s['end']=round(max(e.end for e in inside)/1000+3,3)
 s['evidence']='原片配套英文字幕的演唱标记；已排除访谈段落'
write_json(folder/'locations.json',spans)
print('REFINED',spans,flush=True)
