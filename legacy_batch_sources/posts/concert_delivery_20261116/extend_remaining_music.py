"""Restore observed cut defects serially; release each repaired song separately."""
from pathlib import Path
import fcntl
import traceback
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_check import selection
from workflow.content_repair import extend_observed_music,repair_captions
from posts.concert_delivery_20261116.repair_music_review import BASE as MUSIC_BASE

BASE=Path(__file__).parent

if __name__=='__main__':
    with (BASE/'music-extension.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from posts.concert_delivery_20261116.release_observed_music import tick
        tick()
        q=read_json(BASE/'queue.json');decisions=read_json(BASE/'music-adjudication.json',{})
        status=read_json(BASE/'music-extension-status.json',{})
        for key,decision in decisions.items():
            if (BASE/'REPAIR_PAUSED').exists():break
            q=read_json(BASE/'queue.json')
            if decision.get('status')!='needs_change' or key not in q['blocked_jobs']:continue
            if status.get(key,{}).get('status') in ['passed','repaired']:continue
            slug,name=key.split('/');c=Concert(slug);it=c.item(name);span=selection(c,it)['slice']
            paths=[]
            for edge,cut in zip(['start','end'],span):
                matches=[p for p in (MUSIC_BASE/slug/name).glob(edge+'*.json')
                    if read_json(p).get('planned_cut')==cut]
                if not matches:break
                paths.append(max(matches,key=lambda p:p.stat().st_mtime_ns))
            if len(paths)!=2:continue
            records=[read_json(p) for p in paths]
            if Path(selection(c,it)['source']).suffix.lower()=='.ts' and any(
                    r.get('audio_recipe')!='source_clock_async1_v2' for r in records):continue
            status[key]={'status':'repairing'};write_json(BASE/'music-extension-status.json',status)
            try:
                result=extend_observed_music(c,it,*records)
                if result.get('content'):
                    report=repair_captions(c,it)
                    result['content']=report
                    if report['status']=='passed':
                        with (BASE/'config.lock').open('a') as config_lock:
                            fcntl.flock(config_lock,fcntl.LOCK_EX)
                            current=read_json(BASE/'queue.json');current['blocked_jobs'].pop(key,None)
                            write_json(BASE/'queue.json',current)
                status[key]={k:v for k,v in result.items() if k!='content'}
                if 'content' in result:status[key]['remaining_issues']=result['content']['issues']
                print(key,status[key],flush=True)
            except Exception as error:
                status[key]={'status':'error','error':str(error)};traceback.print_exc()
            write_json(BASE/'music-extension-status.json',status)
