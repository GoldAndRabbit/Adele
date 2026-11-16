"""Apply conservative boundaries observed in continuous original audio."""
from pathlib import Path
import contextlib
import fcntl
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_repair import change_cut
from workflow.content_check import REVIEW,boundary_identity,check
from workflow.source_lyrics import capture

BASE=Path(__file__).parent

def one(slug,span,start_reason,end_reason,evidence,preferred=None):
    c=Concert(slug);it=c.item('10_picture_you');d=c.song_dir(it)
    change_cut(c,it,*span)
    with (BASE/(slug+'-picture-evidence.log')).open('a') as log,contextlib.redirect_stdout(log):
        capture(c,items=[it],workers=2)
    write_json(d/REVIEW,{'input':boundary_identity(c,it),'human_approved':False,
        'resolutions':[],'music':{'status':'passed','method':'machine_original_audio_event_review',
        'start_reason':start_reason,'end_reason':end_reason,
        'evidence':[str(p.resolve()) for p in evidence]}})
    r=check(c,it);print(slug,r['status'],r['issues'],flush=True)
    if r['status']=='passed':
        with (BASE/'config.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            q=read_json(BASE/'queue.json');key=slug+'/'+it['name']
            q['blocked_jobs'].pop(key,None)
            if preferred:q.setdefault('preferred_machine',{})[key]=preferred
            write_json(BASE/'queue.json',q)

if __name__=='__main__':
    folder=BASE/'music-reviews-v3/chappell_lowlands_2025/10_picture_you'
    one('chappell_lowlands_2025',[2765.0,3055.0],
        '连续原音2750–2885秒中，上一曲电吉他尾声及掌声先结束，随后进入本曲器乐段；模型事件在约2766秒识别出本曲器乐。起点前移至2765，保留已听到的完整器乐，不再从2840秒中途开始。原片独立识别首唱2854.16秒，与旧字幕首唱一致。',
        '原音3025–3105秒开始已是音乐结束后的欢呼；3051秒的Thank you保留完整，3055秒结束位于这一句之后、下一句Thank you for having me今晚之前。旧复核也确认本曲音乐已结束，未裁断尾奏。',
        [folder/'start-2750-2885.json',folder/'start-2750-2885.wav',
         folder/'end-3025-3105.json',folder/'end-3025-3105.wav'],
        'zhaojing@192.168.3.10')
    folder=BASE/'music-reviews-v3/chappell_reading_2025/10_picture_you'
    one('chappell_reading_2025',[1822.0,2089.0],
        '原音1810–1945秒中，上一曲结束后先有掌声，之后进入缓慢钢琴和弦器乐；事件复核在约1823秒识别出该器乐，保守前移至1822秒保留全部已观察前奏。独立原片识别首唱1914秒，所有原歌词字幕整体后移78秒，不以参考歌词杜撰缺唱。',
        '原音2065–2145秒中，本曲末句持续到约2084秒，之后短暂欢呼，约2089秒转换为下一首The Giver的乡村快节奏前奏；独立原片识别下一首首唱2101秒。结尾改为2089，保留本曲结尾并去掉旧范围包含的下一首前奏。',
        [folder/'start-1810-1945.json',folder/'start-1810-1945.wav',
         folder/'end-2065-2145.json',folder/'end-2065-2145.wav'])
