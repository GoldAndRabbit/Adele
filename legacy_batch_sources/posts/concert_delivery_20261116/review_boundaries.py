"""Inspect original audio on both sides of existing cuts, without altering them."""
from pathlib import Path
import json
import numpy as np
import soundfile as sf
from workflow.live.paths import Concert,read_json,write_json
from workflow.content_check import selection,boundary_identity,REVIEW,check
from posts.concert_delivery_20261116.audio_review import extract,ask

BASE=Path(__file__).parent

def one(slug,name):
    c=Concert(slug);it=c.item(name);d=c.song_dir(it);policy=selection(c,it)
    identity=boundary_identity(c,it)
    folder=BASE/'music-reviews-v2'/slug/name;folder.mkdir(parents=True,exist_ok=True)
    import subprocess
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',policy['source']]))
    a,b=policy['slice'];head=[max(0,a-75),min(duration,a+25)];tail=[max(0,b-25),min(duration,b+20)]
    for key,span in [('head',head),('tail',tail)]:
        if not (folder/(key+'.wav')).is_file():extract(policy['source'],*span,folder/(key+'.wav'))
    y,sr=sf.read(folder/'head.wav');z,_=sf.read(folder/'tail.wav');offset=len(y)/sr+2
    marked=np.concatenate([y,np.zeros(2*sr),z])
    marker=.2*np.sin(2*np.pi*880*np.arange(round(sr*.09))/sr)
    for point in [a-head[0],offset+b-tail[0]]:
        i=round(point*sr);stop=min(len(marked),i+len(marker))
        marked[i:stop]=np.clip(marked[i:stop]+marker[:stop-i],-1,1)
    sf.write(folder/'both.wav',marked,sr,subtype='PCM_16')
    cached=read_json(folder/'audio-review.json',{})
    if cached.get('boundary_input')==identity:
        result=cached['result']
    else:
        prompt=(f'只根据实际听到的音频检查《{it["title"]}》前奏尾奏切点。这段音频由两个原片片段组成，中间插入2秒静音。'
          '已在两个计划切点各叠加一声短促880Hz提示音（提示音不来自原片），第一声是开头切点，第二声是结尾切点。'
          '不要把整个录音开头误当作计划切点；必须判断提示音处的音乐是否完整。'
          f'第一段是原片{head[0]:.3f}至{head[1]:.3f}秒，计划开头在本音频{a-head[0]:.3f}秒。'
          f'第二段从本音频{offset:.3f}秒开始，是原片{tail[0]:.3f}至{tail[1]:.3f}秒，计划结尾在本音频{offset+b-tail[0]:.3f}秒。'
          '检查：开头是否切断本曲已开始的前奏或唱句？结尾是否切断本曲未结束的唱句或正在持续的尾奏？'
          '不能只因切点附近有声音就失败：音乐已停后的掌声、讲话、自然过场可以保留；连唱在两曲合理转换点切分也可。'
          '可能含上一首的尾奏，不能把上一首当本曲前奏。不根据录音室歌词推测缺段，不要求修改不影响完整性的多余掌声；没有听清则uncertain，不能凭歌名强行通过。'
          f'如果提出更早或更晚的起点，必须实际处于已听到的原片{head[0]:.3f}至{head[1]:.3f}或{tail[0]:.3f}至{tail[1]:.3f}区间内，不能杜撰区间外时间。'
          '输出JSON {"start":{"status":"passed/failed/uncertain","reason":"具体听到的音乐情况",'
          '"suggested_original_time":数字或null},"end":{"status":"passed/failed/uncertain",'
          '"reason":"具体听到的音乐情况","suggested_original_time":数字或null}}。')
        result=ask(folder/'both.wav',prompt,folder/'audio-review.json')
        record=read_json(folder/'audio-review.json');record['boundary_input']=identity;write_json(folder/'audio-review.json',record)
    music={'status':'passed' if all(result.get(k,{}).get('status')=='passed' and result[k].get('reason') for k in ['start','end']) else 'needs_repair',
           'start_reason':result.get('start',{}).get('reason'),'end_reason':result.get('end',{}).get('reason'),
           'method':'machine_original_audio_guard_band_review',
           'evidence':[str((folder/'both.wav').resolve()),str((folder/'audio-review.json').resolve())]}
    previous=read_json(d/REVIEW,{})
    review={'input':identity,'music':music,'resolutions':previous.get('resolutions',[]) if previous.get('input')==identity else [],'human_approved':False}
    write_json(d/REVIEW,review);report=check(c,it)
    print(slug,name,report['status'],[r['kind'] for r in report['issues']],flush=True)
    if report['status']=='passed':
        import fcntl
        with (BASE/'config.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            config=read_json(BASE/'queue.json');config['blocked_jobs'].pop(slug+'/'+name,None);write_json(BASE/'queue.json',config)
    return report

if __name__=='__main__':
    import sys
    one(sys.argv[1],sys.argv[2])
