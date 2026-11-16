"""Restore concretely observed missing source content, retaining prior translations."""
from pathlib import Path
import contextlib
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_repair import change_cut,translated_units,backup
from workflow.content_check import check
from workflow.source_lyrics import capture
from workflow.song.song_translation_workflow import build_outputs

BASE=Path(__file__).parent

def add_rows(c,it,rows,origin):
    d=c.song_dir(it);r=read_json(d/'subs/translation/result.json')
    if any(u.get('source_evidence')==origin for u in r['units']):return
    added=translated_units(d,rows,BASE/(c.slug+'-'+it['name']+'-prefix-translation.json'))
    for u in added:u['source_evidence']=origin
    old=r['units'];combined=sorted(old+added,key=lambda u:u['start']);old_ids={id(u):u['i'] for u in old};remap={}
    for i,u in enumerate(combined):
        if id(u) in old_ids:remap[old_ids[id(u)]]=i
        u['i']=i
    r['units']=combined
    for key in ('notes','final_notes'):
        r[key]={str(remap[int(k)]):v for k,v in r.get(key,{}).items() if int(k) in remap}
    write_json(d/'subs/translation/result.json',r)
    ls=read_json(d/'subs/lines.json')
    for u in added:ls.append({'start_ms':u['start'],'end_ms':u['end'],'text':u['orig'],
        'qwen':u['heard'],'speech':u['type']=='讲话','removed':False,'verdict':'source_audio_verified'})
    ls.sort(key=lambda x:x['start_ms']);write_json(d/'subs/lines.json',ls)
    build_outputs(d,d/'subs')

def refresh(c,it):
    with (BASE/(c.slug+'-'+it['name']+'-evidence.log')).open('a') as log,contextlib.redirect_stdout(log):
        capture(c,items=[it],workers=2)
    r=check(c,it);print(c.slug,it['name'],r['status'],r['issues'],flush=True)

def casual():
    c=Concert('chappell_reading_2025');it=c.item('06_casual');d=c.song_dir(it)
    change_cut(c,it,1070.0,1300.0)
    evidence=str((BASE/'diagnosis-audio/chappell_reading_2025/06_casual/observation.json').resolve())
    # These windows are grounded in the original word bank and continuous audio
    # review. No song timing or missing verse is copied from another performance.
    source_rows=[
        (1073.48,1075.12,'And this is Casual.','讲话'),
        (1079.64,1083.2,'My friends call me a loser','歌词'),
        (1083.22,1087.08,"'Cause I'm still hanging around",'歌词'),
        (1087.1,1089.96,"I've heard so many rumors",'歌词'),
        (1089.96,1094.48,"That I'm just a girl that you bang on your couch",'歌词'),
        (1094.5,1098.16,'I thought you thought of me better','歌词'),
        (1098.2,1101.88,"Someone you couldn't lose",'歌词'),
        (1101.88,1104.48,'You said, "We\'re not together"','歌词'),
        (1104.48,1108.72,'So now when we kiss, I have anger issues','歌词'),
        (1108.72,1113.28,'You said, "Baby, no"','歌词'),
        (1115.12,1121.04,"Knee-deep in the passenger seat, and you're eating me out",'歌词')]
    add_rows(c,it,[{'start':a-1070,'end':b-1070,'text':text,'type':kind} for a,b,text,kind in source_rows],evidence)
    refresh(c,it)

def guilty():
    c=Concert('chappell_lowlands_2025');it=c.item('05_guilty_pleasure');d=c.song_dir(it)
    change_cut(c,it,1222.0,1480.0)
    evidence=str((BASE/'diagnosis-audio/chappell_lowlands_2025/05_guilty_pleasure/observation.json').resolve())
    r=read_json(d/'subs/translation/result.json')
    if r['units'][0]['orig']=='Wheels turning in my head':
        r['units'][0]['start']=round((1259.24-1222)*1000)
        write_json(d/'subs/translation/result.json',r)
        ls=read_json(d/'subs/lines.json');ls[0]['start_ms']=r['units'][0]['start'];write_json(d/'subs/lines.json',ls)
    add_rows(c,it,[{'start':1255.48-1222,'end':1259.08-1222,'text':'Learned it on the internet','type':'歌词'}],evidence)
    refresh(c,it)

def good_luck():
    c=Concert('chappell_reading_2025');it=c.item('15_good_luck_babe');d=c.song_dir(it)
    change_cut(c,it,2600.0,2803.0)
    r=read_json(d/'subs/translation/result.json')
    for u in r['units']:
        if u['orig']=='Well' and not (u.get('v3_final') or u.get('v2_final')):
            u['type']='语气词'
    write_json(d/'subs/translation/result.json',r);build_outputs(d,d/'subs')
    refresh(c,it)

if __name__=='__main__':
    casual();guilty();good_luck()
