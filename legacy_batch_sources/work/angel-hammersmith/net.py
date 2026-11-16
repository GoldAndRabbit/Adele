import requests,json,concurrent.futures,time
from pathlib import Path
base=Path('work/angel-hammersmith')
info=json.loads((base/'review-source.info.json').read_text())
formats={f['format_id']:f for f in info['formats']}
proxy={'https':'http://127.0.0.1:7890','http':'http://127.0.0.1:7890'}
def fetch(fmt,a,b):
 f=formats[fmt];headers=f.get('http_headers',info['http_headers']).copy();headers['Range']=f'bytes={a}-{b}'
 r=requests.get(f['url'],headers=headers,proxies=proxy,timeout=(10,20))
 if r.status_code not in (200,206) or len(r.content)!=b-a+1:raise RuntimeError(f'{r.status_code} length={len(r.content)}')
 return r.content
if __name__=='__main__':
 def test(n):
  t=time.monotonic()
  try:print(n,len(fetch(n,0,65535)),round(time.monotonic()-t,1),flush=True)
  except Exception as e:print(n,type(e).__name__,str(e).split('https')[0][:100],flush=True)
 with concurrent.futures.ThreadPoolExecutor(5) as ex:list(ex.map(test,['401','137','399','140','251']))
