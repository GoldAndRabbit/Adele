"""Record source-audio observations using the provider's documented Omni API."""
from pathlib import Path
import base64, json, os, re, subprocess
from openai import OpenAI
from workflow.llm import load_env, PROVIDERS
from workflow.live.paths import write_json

MODEL='qwen3.8-omni-flash'

def extract(source, start, end, output):
    subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(start),'-i',str(source),
                    '-t',str(end-start),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(output)],check=True)

def ask(path, prompt, output):
    load_env()
    endpoint,key,_=PROVIDERS['aliyun']
    client=OpenAI(base_url=endpoint,api_key=os.environ[key],timeout=180,max_retries=1)
    encoded=base64.b64encode(Path(path).read_bytes()).decode()
    stream=client.chat.completions.create(model=MODEL,reasoning_effort='none',modalities=['text'],stream=True,
      messages=[{'role':'user','content':[{'type':'input_audio','input_audio':{'data':'data:audio/wav;base64,'+encoded,'format':'wav'}},
      {'type':'text','text':prompt}]}])
    text=''
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            text+=chunk.choices[0].delta.content
    Path(output).with_suffix('.response.txt').write_text(text)
    body=re.search(r'\{.*\}',text,re.S)
    if not body:raise ValueError('Audio reviewer did not return JSON')
    # Some responses omit the opening quote on a property (e.g. ,end":).
    # Repair syntax only; retain the untouched response beside the evidence.
    payload=re.sub(r'([,{])\s*([A-Za-z_][A-Za-z_0-9]*)"\s*:',r'\1"\2":',body[0])
    result=json.loads(payload)
    record={'model':MODEL,'audio':str(Path(path).resolve()),'prompt':prompt,'result':result,
            'documentation':'https://www.alibabacloud.com/help/en/model-studio/qwen-omni',
            'human_review':False}
    write_json(output,record)
    return result

if __name__=='__main__':
    from workflow.live.paths import Concert
    c=Concert('singles');it=c.item('khalid_young_dumb_broke_mv_ipfjnp1gupc')
    from workflow.content_check import selection
    b=Path(__file__).parent
    extract(selection(c,it)['source'],218,247.061,b/'mv-tail.wav')
    result=ask(b/'mv-tail.wav',
      'Listen to this actual music-video ending, not any reference lyrics. It begins at original-video 218 seconds. '
      'Transcribe every clearly heard spoken or sung sentence. Distinguish the spoken comedy dialogue from the sung refrain. '
      'Do not fill in a known song lyric when a person is talking. Return JSON only: '
      '{"sentences":[{"start":seconds_relative_to_this_clip,"end":seconds_relative_to_this_clip,"text":"exact English heard",'
      '"type":"speech or singing"}],"observations":"what actually happens in this audio"}.',b/'mv-tail-review.json')
    print('Audio observations saved; sentences',len(result.get('sentences',[])),flush=True)
