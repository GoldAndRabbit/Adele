import sys,time,tempfile,json
from pathlib import Path
from workflow.live.paths import ROOT,Concert,read_json,write_json
from workflow import dual_render as render
from workflow.dual_platform import encode_job,probe
mode=sys.argv[1];channel=sys.argv[2];slug=sys.argv[3] if len(sys.argv)>3 else 'chappell_lolla_brasil_2026'
c=Concert(slug);item=c.song_items()[0];d=c.song_dir(item)
b=ROOT/'work/stream_delivery_20261115';out=b/(slug+'-'+mode+'-'+channel);out.mkdir(exist_ok=True)
policy=dict(read_json(c.dir/'vertical_source.json')['songs'][item['name']]);policy['slice']=[policy['slice'][0],policy['slice'][0]+8]
policy.update(delivery_platforms=[channel],single_channel_pipeline=mode)
render.configure(c,item,out);render.assets()
start=time.monotonic()
with tempfile.TemporaryDirectory(prefix='stream-test-',dir=Path.home()/'Library/Caches/adele') as tmp:
 cache=Path(tmp)
 encode_job(policy,Path(policy['source']),out,cache,d)
 media=read_json(out/'products.json');row=media['items'][0];info=probe(out/row['file'])
 intermediate_videos=[str(x) for x in cache.rglob('*') if x.suffix in ('.mkv','.mp4','.png','.jpg')]
 result={'mode':mode,'channel':channel,'concert':slug,'seconds':round(time.monotonic()-start,3),'staged_video_or_frames':intermediate_videos,'items':media['items'],'streams':[{k:s.get(k) for k in ('codec_type','codec_name','width','height','avg_frame_rate','duration','sample_rate','bits_per_raw_sample')} for s in info['streams']],'timings':media['timings']}
 write_json(out/'result.json',result);print('RESULT',json.dumps(result,ensure_ascii=False))
