"""Resume caption adjudication song by song; a failed song never stops the rest."""
from pathlib import Path
import fcntl
import traceback
from datetime import datetime
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_repair import repair_captions
from workflow.content_check import check

BASE=Path(__file__).parent

def main():
    with (BASE/'caption-repair.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from posts.concert_delivery_20261116.release_observed_music import tick
        tick()
        queue=read_json(BASE/'queue.json');status=read_json(BASE/'caption-repair-status.json',{})
        for key in queue['blocked_jobs']:
            if (BASE/'REPAIR_PAUSED').exists():return
            slug,name=key.split('/')
            status[key]={'started_at':datetime.now().astimezone().isoformat(),'status':'reviewing'}
            write_json(BASE/'caption-repair-status.json',status)
            try:
                c=Concert(slug)
                report=repair_captions(c,c.item(name))
                status[key].update(status=report['status'],issues=report['issues'],finished=True,
                    fingerprint=report['fingerprint'])
                if report['status']=='passed':
                    with (BASE/'config.lock').open('a') as config_lock:
                        fcntl.flock(config_lock,fcntl.LOCK_EX)
                        config=read_json(BASE/'queue.json');config['blocked_jobs'].pop(key,None)
                        write_json(BASE/'queue.json',config)
                else:
                    with (BASE/'config.lock').open('a') as config_lock:
                        fcntl.flock(config_lock,fcntl.LOCK_EX)
                        config=read_json(BASE/'queue.json')
                        config['blocked_jobs'][key]={'reason':'content_findings',
                            'kinds':sorted({x['kind'] for x in report['issues']}),
                            'report':str((c.song_dir(c.item(name))/'reports/content_check.json').resolve())}
                        write_json(BASE/'queue.json',config)
                print(key,report['status'],[x['kind'] for x in report['issues']],flush=True)
            except Exception as error:
                status[key].update(status='error',error=str(error));traceback.print_exc()
            status[key]['finished_at']=datetime.now().astimezone().isoformat()
            write_json(BASE/'caption-repair-status.json',status)

if __name__=='__main__':main()
