"""Run one paced archive at a time; scheduled reports are independent."""
import argparse
from datetime import datetime
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from post_bili.title_tick import JOB,SH
from workflow.live.paths import read_json,write_json


def wait_delay(pacing,current):
    due=pacing.get('next_attempt_after')
    if not due:
        return 0
    return max(0,(datetime.fromisoformat(due)-current).total_seconds())


def blocked_reason(pacing):
    if pacing.get('status')=='preservation_check_failed':
        return '保护字段校验失败，停止写入'
    if pacing.get('status')=='needs_check':
        return '上一首执行异常，需要检查，不自动重复提交'
    output=pacing.get('last_output','')
    if any(s in output for s in ('账号未登录','帐号未登录','还没登录','登录失效')):
        return '需要恢复登录'
    return ''


def save_status(status,**extra):
    progress=read_json(JOB/'progress.json',{})
    write_json(JOB/'queue-status.json',{'pid':os.getpid(),'status':status,
               'updated_at':datetime.now(SH).isoformat(),'counts':progress.get('counts',{}),**extra})


def worker():
    with (JOB/'.title-queue.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('已有后台逐首队列，本次不重复启动',flush=True)
            return
        save_status('running')
        while True:
            pacing=read_json(JOB/'pacing.json',{})
            if pacing.get('status')=='complete':
                save_status('complete')
                print('逐首队列已全部完成',flush=True)
                return
            reason=blocked_reason(pacing)
            if reason:
                save_status('needs_review',reason=reason)
                print(reason,flush=True)
                return
            delay=wait_delay(pacing,datetime.now(SH))
            if delay>0:
                save_status('platform_cooldown' if pacing.get('status')=='platform_cooldown' else 'waiting',
                            next_attempt_after=pacing['next_attempt_after'])
                time.sleep(min(60,delay+0.05))
                continue
            previous=pacing.get('finished_at')
            save_status('processing_one')
            result=subprocess.run([ROOT/'.venv/bin/python','-u',ROOT/'post_bili/title_tick.py'],cwd=ROOT)
            if result.returncode:
                save_status('needs_review',reason='逐首执行器异常退出',exit_code=result.returncode)
                return
            updated=read_json(JOB/'pacing.json',{})
            if updated.get('finished_at')==previous and updated.get('status')!='complete':
                # Another worker may hold a lock. Never busy-loop around it.
                time.sleep(60)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',action='store_true')
    args=parser.parse_args()
    JOB.mkdir(exist_ok=True)
    if not args.start:
        worker()
        return
    reason=blocked_reason(read_json(JOB/'pacing.json',{}))
    if reason:
        raise SystemExit(reason)
    with (JOB/'.title-queue.lock').open('a') as check:
        try:
            fcntl.flock(check,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('后台逐首队列已在运行')
            return
    with (JOB/'queue.log').open('a') as log:
        child=subprocess.Popen([ROOT/'.venv/bin/python','-u',Path(__file__).resolve()],cwd=ROOT,
                               stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                               start_new_session=True)
    print('已启动后台逐首队列 PID',child.pid)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        from post_bili.edit_description import redacted_error
        save_status('needs_review',reason=redacted_error(exc))
        raise SystemExit(redacted_error(exc))
