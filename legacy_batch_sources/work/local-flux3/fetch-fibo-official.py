import concurrent.futures as cf, hashlib, json, os, pathlib, time, urllib.request as req
root=pathlib.Path('/Volumes/harddisk_5T/adele-workflow/work/flux3/models/fibo2-edit-turbo-bf16')
assert os.path.ismount('/Volumes/harddisk_5T')
repo='ml-resources/Fibo-2.0-edit-turbo'
data=json.loads(pathlib.Path('work/local-flux3/fibo-official.manifest.json').read_text())
rev=data['sha']
print(rev,flush=True)
parts=[]
files=[]
for item in data['siblings']:
 p=root/item['rfilename']; p.parent.mkdir(parents=True,exist_ok=True)
 files.append((p,item))
 for n in range(0,item['size'],16*1024**2):
  parts.append((item['rfilename'],n,min(n+16*1024**2,item['size'])-1))
def get(part):
 path,start,end=part
 tmp=pathlib.Path('work/local-flux3/fibo-chunks')/path/str(start)
 if tmp.exists() and tmp.stat().st_size==end-start+1:return
 tmp.parent.mkdir(parents=True,exist_ok=True)
 pending=tmp.with_suffix(".incomplete")
 for attempt in range(10):
  try:
   pos=start+(pending.stat().st_size if pending.exists() else 0)
   if pos>end:
    os.replace(pending,tmp);return
   url=f'https://www.modelscope.cn/models/briaai/Fibo-2.0-edit-turbo/resolve/master/{path}?part={pos}&end={end}'
   with req.urlopen(req.Request(url,headers={'Range':f'bytes={pos}-{end}'}),timeout=90) as r:
    assert (r.status==206 and r.headers.get('Content-Range','').startswith(f'bytes {pos}-{end}/')) or (r.status==200 and pos==0 and end+1==next(x['size'] for x in data['siblings'] if x['rfilename']==path))
    with pending.open('ab') as out:
     while block:=r.read(128*1024):out.write(block)
   assert pending.stat().st_size==end-start+1
   os.replace(pending,tmp);return
  except Exception as exc:
   print(path,start,attempt,type(exc).__name__,flush=True)
   if attempt==9:raise
   time.sleep(min(8, attempt+1))
with cf.ThreadPoolExecutor(36) as ex:
 for i,_ in enumerate(ex.map(get,parts)):
  if i%25==0:print(i+1,len(parts),flush=True)
for p,item in files:
 digest=hashlib.sha256() if 'lfs' in item else hashlib.sha1(f"blob {item['size']}\0".encode())
 tmp=p.with_suffix('.assembling')
 with tmp.open('wb') as out:
  for n in range(0,item['size'],16*1024**2):
   chunk=pathlib.Path('work/local-flux3/fibo-chunks')/item['rfilename']/str(n); b=chunk.read_bytes(); digest.update(b);out.write(b)
 expected=item['lfs']['sha256'] if 'lfs' in item else item['blobId']
 assert digest.hexdigest()==expected,p
 os.replace(tmp,p)
 for chunk in (pathlib.Path('work/local-flux3/fibo-chunks')/item['rfilename']).iterdir():chunk.unlink()
