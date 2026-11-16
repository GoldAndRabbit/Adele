from net import *
import sys,os
def download(fmt):
 f=formats[fmt];size=f['filesize'];chunks=base/('parts-'+fmt);chunks.mkdir(exist_ok=True);step=512*1024
 def one(start):
  end=min(size,start+step)-1;path=chunks/str(start)
  if path.exists() and path.stat().st_size==end-start+1:return
  for k in range(5):
   try:path.write_bytes(fetch(fmt,start,end));return
   except Exception as e:
    if k==4:raise RuntimeError(f'{fmt}, offset {start}, {type(e).__name__}')
 with concurrent.futures.ThreadPoolExecutor(12) as pool:list(pool.map(one,range(0,size,step)))
 with (base/(fmt+'.media')).open('wb') as out:
  for start in range(0,size,step):out.write((chunks/str(start)).read_bytes())
 print(fmt,'done',flush=True)
with concurrent.futures.ThreadPoolExecutor(2) as ex:list(ex.map(download,sys.argv[1:]))
