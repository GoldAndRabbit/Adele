exec(open('work/grammy-ts60/listen.py').read().split('for name,t,dur')[0])
p=Path('work/grammy-ts-review')
for name,t,dur in [('invisible-head',1243,30),('one-joins',7448,15),('one-lastjoin',7579,12),('pink-start',3414,12)]:
 arr=resample_poly(pcm[t*8000:(t+dur)*8000].astype(np.float32)/32768,2,1)
 r=mlx_whisper.transcribe(arr,path_or_hf_repo=model,language='en',word_timestamps=True,condition_on_previous_text=False,temperature=0,initial_prompt='Live singing at the Grammy Awards.')
 (p/(name+'.json')).write_text(json.dumps(r['segments'],default=float,indent=1))
 print(name,[(round(t+s['start'],2),s['text']) for s in r['segments']],flush=True)
