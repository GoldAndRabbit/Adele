import subprocess as sp,time,json,hashlib,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from scipy.signal import correlate,correlation_lags
sys.path.insert(0,str(Path.cwd()));sys.path.insert(0,str(Path('work/dual-dark-horse').resolve()))
from render_products import W,D,START,DURATION,render,save,timing
p=W/'products.json'
def progress(message):save(p,{'status':'running','stage':message,'items':[]})
progress('共享60fps母版插帧中')
while not (W/'master-manifest.json').exists():time.sleep(2)
progress('共享母版已验证；正在合成抖音1080p60成品')
render('portrait')
progress('抖音版编码完成；正在合成B站4K60成品')
render('landscape')
progress('两版编码完成；正在核验帧率、完整解码、音画时钟')
t=time.monotonic();checks=[];items=[]
def probe(path):return json.loads(sp.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
def pcm(path,start,duration):
 raw=sp.check_output(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-ss',str(start),'-i',str(path),'-t',str(duration),'-vn','-ac','1','-ar','8000','-f','f32le','-']);return np.frombuffer(raw,np.float32)
for platform,file,size in [('bilibili','bilibili-4k60.mp4',(3840,2160)),('douyin','douyin-1080p60.mp4',(1080,1920))]:
 path=W/file;info=probe(path);v=next(x for x in info['streams'] if x['codec_type']=='video');a=next(x for x in info['streams'] if x['codec_type']=='audio');assert (v['width'],v['height'])==size;assert v['avg_frame_rate']=='60/1';assert abs(float(v['duration'])-DURATION)<1/60+.002;assert abs(float(a['duration'])-DURATION)<.04
 with (W/f'{platform}-validation.log').open('w') as log:sp.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-xerror','-i',str(path),'-map','0:v:0','-map','0:a:0','-f','null','-'],stderr=log,check=True)
 offsets=[]
 for point in [5,90,195]:
  ref=pcm(W/'native50.mkv',point+START,4);actual=pcm(path,point,4);corr=correlate(actual,ref,mode='full',method='fft');lags=correlation_lags(len(actual),len(ref));valid=np.abs(lags)<=400;lag=int(lags[valid][np.argmax(corr[valid])]);offsets.append(lag/8000)
 assert max(abs(x) for x in offsets)<=1/60,offsets
 checks.append({'platform':platform,'audio_offsets_seconds':offsets,'full_decode':'passed','video_frames':int(v.get('nb_frames',0)),'duration':v['duration'],'width':size[0],'height':size[1],'fps':'60/1'})
 timings=json.loads((W/'timings.json').read_text());sec=next(x['seconds'] for x in timings if x['stage']==file.removesuffix('.mp4')+'_render_encode')
 items.append({'platform':platform,'file':file,'width':size[0],'height':size[1],'fps':60,'status':'ready','duration':float(v['duration']),'render_seconds':sec,'bit_rate':int(v.get('bit_rate',0)),'start':START})
timing('verify_both_outputs_decode_and_audio_clock',time.monotonic()-t)
save(W/'validation.json',checks)
all_t=[json.loads((W/'prepare-timing.json').read_text())]+json.loads((W/'master-timings.json').read_text())+json.loads((W/'timings.json').read_text())
labels={'source_decode_deinterlace_lossless':'原片解码、去隔行、无损保存','stage_lossless_input_on_local_ssd':'母版输入迁入本地及校验','scene_boundary_detection':'切镜边界检测','interpolate50to60_and_lossless_master':'50→60插帧与无损母版写入','verify_master':'共享母版完整解码验证','prepare_titles_subtitles_masks':'标题、字幕与渐变素材','bilibili-4k60_render_encode':'B站4K60合成编码','douyin-1080p60_render_encode':'抖音1080p60合成编码','verify_both_outputs_decode_and_audio_clock':'双版完整解码及音频时钟校验'}
for row in all_t:row['label']=labels.get(row['stage'],row['stage'])
first=all_t[0];wall=time.time()-(first['created']-first['seconds'])
manifest={'status':'ready','items':items,'created_local':datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),'production_seconds':wall,'timings':all_t,'engine':'Apple VideoToolbox 质量优先 · 50→60fps · 切镜保护 · 共享一次插帧','master':'master60.mkv','wall_time_note':'总耗时为此次从源准备到成品验证的墙钟时间，包含迁移、短样比较和排版调试；各阶段单列。','validation':checks,'source_policy':json.loads(Path('concerts/grammys_2014/vertical_source.json').read_text())['songs']['04_dark_horse']}
save(p,manifest)
print('BOTH VERIFIED READY',json.dumps(items,ensure_ascii=False),flush=True)
