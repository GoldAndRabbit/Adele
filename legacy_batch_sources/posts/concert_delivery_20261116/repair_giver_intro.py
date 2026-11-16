"""Use the observed Picture You → The Giver broadcast transition."""
from pathlib import Path
import contextlib
import fcntl
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_repair import change_cut
from workflow.content_check import REVIEW,boundary_identity,check
from workflow.source_lyrics import capture

BASE=Path(__file__).parent
if __name__=='__main__':
    c=Concert('chappell_reading_2025');it=c.item('12_the_giver');d=c.song_dir(it)
    change_cut(c,it,2089.0,2300.0)
    with (BASE/'giver-evidence.log').open('a') as log,contextlib.redirect_stdout(log):
        capture(c,items=[it],workers=2)
    p=BASE/'music-reviews-v3/chappell_reading_2025/10_picture_you'
    old=BASE/'music-reviews/chappell_reading_2025/12_the_giver'
    write_json(d/REVIEW,{'input':boundary_identity(c,it),'human_approved':False,'resolutions':[],
        'music':{'status':'passed','method':'machine_continuous_source_transition_review',
        'start_reason':'相邻连续原音2065–2145秒：Picture You唱句约2084秒结束，掌声后约2089秒进入The Giver的乡村快节奏器乐，原片首唱2101秒。起点从2100前移到2089，恢复该器乐，旧字幕完整后移11秒。原先失败的串接复核误将音频开头2080秒的上一曲唱句当作计划切点。',
        'end_reason':'独立原片识别和原音尾段复核均显示本曲末句You are welcome于2287秒前结束，2300秒切点位于音乐结束后的欢呼过场，未截断唱句或尾奏。',
        'evidence':[str((p/'end-2065-2145.wav').resolve()),str((p/'end-2065-2145.json').resolve()),
                    str((old/'tail.wav').resolve()),str((old/'audio-review.json').resolve())]}})
    r=check(c,it);print(r['status'],r['issues'],flush=True)
    if r['status']=='passed':
        with (BASE/'config.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);q=read_json(BASE/'queue.json')
            q['blocked_jobs'].pop(c.slug+'/'+it['name'],None);write_json(BASE/'queue.json',q)
