import concurrent.futures as cf, hashlib, json, os, pathlib, time, urllib.request as req
root=pathlib.Path('/Volumes/harddisk_5T/adele-workflow/work/flux3/models/klein-mlx-4bit')
assert os.path.ismount('/Volumes/harddisk_5T')
repo='vanch007/FLUX.3-Image-Klein-mlx-4bit'
data=json.load(req.urlopen(f'https://huggingface.co/api/models/{repo}?blobs=true'))
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
 tmp=root/'.chunks'/path/str(start)
 if tmp.exists() and tmp.stat().st_size==end-start+1:return
 tmp.parent.mkdir(parents=True,exist_ok=True)
 pending=tmp.with_suffix(".incomplete")
 for attempt in range(10):
  try:
   pos=start+(pending.stat().st_size if pending.exists() else 0)
   if pos>end:
    os.replace(pending,tmp);return
   url=f'https://huggingface.co/{repo}/resolve/{rev}/{path}?part={pos}&end={end}'
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
   chunk=root/'.chunks'/item['rfilename']/str(n); b=chunk.read_bytes(); digest.update(b);out.write(b)
 expected=item['lfs']['sha256'] if 'lfs' in item else item['blobId']
 assert digest.hexdigest()==expected,p
 os.replace(tmp,p)
 for chunk in (root/'.chunks'/item['rfilename']).iterdir():chunk.unlink()
