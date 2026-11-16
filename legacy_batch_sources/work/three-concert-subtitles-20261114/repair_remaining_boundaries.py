"""Recover five preview-only ranges using reference lyrics and source timestamps.

The ranges stay pending review; this never approves or renders final products.
"""
import sys,re,traceback,subprocess
from pathlib import Path
sys.path[:0]=['/Users/gold/repos/adele','/Users/gold/repos/adele/workflow','/Users/gold/repos/adele/work/coachella-lolla-previews']
import common
from rapidfuzz import fuzz
from workflow.live.paths import read_json,write_json,Concert
base=Path(__file__).resolve().parent
common.REFS.update(common.reusable_refs())
jobs={j['slug']:j for j in read_json(common.BASE/'jobs.json')}
fixed=[]
for slug in ['adele_one_night_only_2021','gaga_coachella_2025']:
 c=Concert(slug);folder=common.BASE/slug;rows=read_json(folder/'transcript.json');evidence=read_json(base/('remaining-location-'+slug+'.json'))
 spans=read_json(folder/'locations.json');old={x['idx'] for x in spans}
 backup=folder/'locations.before_missing_repair.json'
 if not backup.exists():write_json(backup,spans)
 for candidate in evidence['items']:
  if not candidate.get('found') or candidate['idx'] in old:continue
  it=next(i for i in c.song_items() if i['idx']==candidate['idx']);d=c.song_dir(it)
  try:
   common.reference(jobs[slug],it,c)
   lyrics=[common.norm(x) for x in (d/'lyrics.txt').read_text().splitlines() if len(common.norm(x).split())>=4]
   near=[r for r in rows if candidate['first']-120<=r['t']<=candidate['last']+120]
   matches=[]
   for row in near:
    heard=common.norm(row['text'])
    scores=[(fuzz.partial_ratio(line,heard),line) for line in lyrics if len(heard.split())>=4]
    if scores and max(scores)[0]>=88:matches.append(dict(t=row['t'],end=row['end'],score=max(scores)[0]))
   if len(matches)<2:raise ValueError('Not enough lyric anchors')
   start=max(0,matches[0]['t']-2);end=min(c.load('info')['duration'],matches[-1]['end']+3)
   if not 60<=end-start<=600:raise ValueError('Unsupported candidate duration')
   # Keep evidence and the original catalog item; a later review can refine edges.
   span={'idx':it['idx'],'start':start,'end':end,'artist_zh':it.get('artist_zh') or c.load('info').get('artist_zh'),'evidence':'参考歌词与原片ASR多个锚点匹配，预览首尾待审核','anchors':matches}
   spans.append(span);write_json(folder/'locations.json',sorted(spans,key=lambda s:s['start']));fixed.append((slug,it['name']));print('RANGE_RECOVERED',slug,it['name'],start,end,flush=True)
  except Exception as exc:print('RANGE_STILL_PENDING',slug,it['name'],str(exc),flush=True)
write_json(base/'recovered-boundaries.json',fixed)
if fixed:
 print('RESUMING_SUBTITLES_FOR_RECOVERED_RANGES',flush=True)
 subprocess.run([str(Path('/Users/gold/repos/adele/.venv/bin/python')),'-u',str(base/'run.py')],cwd='/Users/gold/repos/adele',check=True)
