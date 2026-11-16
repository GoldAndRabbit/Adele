"""One archive per trigger, with a persistent gap and platform cooldown."""
from datetime import datetime,timedelta
import fcntl
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from workflow.live.paths import read_json,write_json

JOB=ROOT/'posts/bili_title_sync_20261116'
ALBUM=ROOT/'posts/bili_album_correction_20261116'
STATE=JOB/'pacing.json'
SH=ZoneInfo('Asia/Shanghai')
GAP_SECONDS=60
COOLDOWN_SECONDS=1800


def allowed(state,current):
    due=state.get('next_attempt_after')
    if state.get('status')=='preservation_check_failed':
        return False,'保护字段核验失败，停止自动写入，需人工处理'
    if due and current<datetime.fromisoformat(due):
        return False,'等待至 '+due
    return True,''


def choose_action(progress,album):
    if album.get('status')!='verified':
        return 'album'
    if progress.get('counts',{}).get('verified',0)<378:
        return 'title'
    return 'done'


def finish(state,output,success,current):
    blocked=any(code in output for code in ('412 Client Error',' -702','检测到风险行为'))
    unsafe=any(msg in output for msg in ('preservation_check_failed','封面发生变化','线上封面发生变化',
                                        '标题发生变化','视频发生变化','完整简介发生变化'))
    state.update(finished_at=current.isoformat(),last_output=output[-3500:])
    if unsafe:
        state['status']='preservation_check_failed'
    else:
        state['status']='platform_cooldown' if blocked else 'waiting_for_next_item' if success else 'needs_check'
    state['next_attempt_after']=(current+timedelta(seconds=COOLDOWN_SECONDS if blocked else GAP_SECONDS)).isoformat()
    return state


def main():
    JOB.mkdir(exist_ok=True)
    with (JOB/'.item-pace.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('已有逐首任务运行，本次不重复启动')
            return
        state=read_json(STATE,{})
        current=datetime.now(SH)
        can_run,reason=allowed(state,current)
        if not can_run:
            print(reason)
            return
        progress=read_json(JOB/'progress.json',{})
        action=choose_action(progress,read_json(ALBUM/'online-description-update.json',{}))
        if action=='done':
            from post_bili.sync_titles import pin_local
            pin_local(read_json(JOB/'manifest.json'),progress['records'],JOB)
            blocker=read_json(JOB/'blocker.json',{})
            blocker.update(status='resolved',resolved_at=current.isoformat())
            write_json(JOB/'blocker.json',blocker)
            state.update(status='complete',finished_at=current.isoformat())
            write_json(STATE,state)
            print('DONE: 378条标题全部核验，专辑归属纠错已核验')
            return
        # The child title worker has its own lock. Check it before starting a
        # description edit too, so this controller cannot race a bulk worker.
        with (JOB/'.title-sync.lock').open('a') as check:
            try:
                fcntl.flock(check,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                print('已有标题任务运行，本次不重复启动')
                return
        state.update(status='running',action=action,started_at=current.isoformat(),
                     next_attempt_after=(current+timedelta(seconds=GAP_SECONDS)).isoformat(),
                     min_gap_seconds=GAP_SECONDS,cooldown_seconds=COOLDOWN_SECONDS)
        write_json(STATE,state)
        if action=='album':
            cmd=[ROOT/'.venv/bin/python',ROOT/'post_bili/correct_maggots_album.py','--submit']
        else:
            cmd=[ROOT/'.venv/bin/python','-u',ROOT/'post_bili/sync_titles.py',
                 ROOT/'outputs/01a1ab7a-b3c2-7212-a2fb-a82a18052c77/.build/review-data.json',
                 JOB,'--submit','--interval','2','--limit','1','--pin-local']
        try:
            result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=180)
            output=result.stdout+'\n'+result.stderr
            success=result.returncode==0
        except subprocess.TimeoutExpired:
            output='本首操作超时，保留提交意图，下一轮先回读，不能重复提交'
            success=False
        state=finish(state,output,success,datetime.now(SH))
        write_json(STATE,state)
        with (JOB/'per-item.log').open('a') as log:
            log.write(state['finished_at']+' '+action+' '+state['status']+'\n'+output+'\n')
        print(output.strip())
        print('本次只处理1首；下次最早：'+state['next_attempt_after'])


if __name__=='__main__':
    main()
