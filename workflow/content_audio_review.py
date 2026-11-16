"""Cached, auditable observations of actual audio. Never supplies studio lyrics."""
from pathlib import Path
import base64
import json
import os
import re
import subprocess
import fcntl
import hashlib
import shutil
import time
import httpx

from openai import OpenAI, APIConnectionError
from workflow.llm import PROVIDERS, load_env
from workflow.live.paths import read_json, write_json

MODEL = 'qwen3.8-omni-flash'

def cached_audio(source):
    """Decode an original once; repeated review windows use small internal audio.

    The master remains on the external disk. This lossless mono/16k ASR cache is
    disposable, keyed to the original stat identity, and never used for delivery.
    """
    p=Path(source).resolve()
    if p.suffix.lower() not in ('.ts','.mkv','.mp4','.mov','.webm'):
        return p
    st=p.stat();identity={'path':str(p),'device':st.st_dev,'inode':st.st_ino,
        'size':st.st_size,'mtime_ns':st.st_mtime_ns,'ctime_ns':st.st_ctime_ns}
    identity['audio_recipe']='mono16k_flac_source_clock_async1_v2'
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:24]
    root=Path.home()/'Library/Caches/adele/content-review-audio';root.mkdir(parents=True,exist_ok=True)
    output=root/(key+'.flac');binding=root/(key+'.json')
    with (root/(key+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not output.is_file() or read_json(binding,{})!=identity:
            tmp=root/(key+'.pending.flac')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(p),'-vn','-map','0:a:0',
                '-af','aresample=async=1:first_pts=0','-ac','1','-ar','16000','-c:a','flac','-y',str(tmp)],check=True)
            tmp.replace(output);write_json(binding,identity)
    return output

def extract(source, start, end, output):
    if end <= start:
        raise ValueError('Empty original-audio review interval')
    source=cached_audio(source)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(start),'-i',str(source),
        '-t',str(end-start),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(output)],check=True)

def _ask_once(audio, prompt, output):
    load_env()
    endpoint, key, _ = PROVIDERS['aliyun']
    client = OpenAI(base_url=endpoint,api_key=os.environ[key],timeout=180,max_retries=1)
    encoded = base64.b64encode(Path(audio).read_bytes()).decode()
    stream = client.chat.completions.create(model=MODEL,reasoning_effort='none',
        modalities=['text'],stream=True,messages=[{'role':'user','content':[
            {'type':'input_audio','input_audio':{'data':'data:audio/wav;base64,'+encoded,'format':'wav'}},
            {'type':'text','text':prompt}]}])
    response = ''.join(chunk.choices[0].delta.content or '' for chunk in stream if chunk.choices)
    Path(output).with_suffix('.response.txt').write_text(response)
    body = re.search(r'\{.*\}',response,re.S)
    if not body:
        raise ValueError('Audio observer returned no JSON')
    payload = re.sub(r'([,{])\s*([A-Za-z_][A-Za-z_0-9]*)"\s*:',r'\1"\2":',body[0])
    result = json.loads(payload)
    write_json(output,{'model':MODEL,'audio':str(Path(audio).resolve()),'prompt':prompt,
        'result':result,'human_review':False,
        'documentation':'https://www.alibabacloud.com/help/en/model-studio/qwen-omni'})
    return result

def ask(audio,prompt,output):
    # SDK retries do not restart an already-open SSE stream after Broken pipe.
    # Retry the observation, preserving each failed response; never synthesize a
    # passing observation from a network/JSON error.
    for attempt in range(3):
        try:return _ask_once(audio,prompt,output)
        except (APIConnectionError,httpx.HTTPError,json.JSONDecodeError):
            raw=Path(output).with_suffix('.response.txt')
            if raw.exists():shutil.copy2(raw,Path(output).with_suffix(f'.attempt-{attempt+1}.response.txt'))
            if attempt==2:raise
            time.sleep(attempt+1)
