import pathlib,subprocess,time,json,os,fcntl
b=pathlib.Path(__file__).parent;p='.venv/bin/python'
lock=(b/'added.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
s={'pid':os.getpid(),'jobs':{}}
def save(stage):
 s['stage']=stage;(b/'prepare_added_status.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
save('references')
subprocess.run([p,str(b/'fetch_added_references.py')],check=True)
for n in ['next_20261031_2z3euy1axdy','next_20261031_jn2kgdpozz4']:
 s['current']=n
 if not (pathlib.Path('posts')/n/'lyrics.txt').exists():
  s['jobs'][n]='reference_incomplete';save('needs_reference_followup');continue
 while True:
  q=(b/'queue.lock').open('a')
  try:fcntl.flock(q,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:
   q.close();save('waiting_existing_queue');time.sleep(20);continue
  q.close()
  save('preparing')
  r=subprocess.run([p,'-u',str(b/'run.py'),'--prepare-now','--only',n])
  if r.returncode:time.sleep(20);continue
  state=json.loads((b/'status.json').read_text());s['jobs'][n]=state['jobs'].get(n,{});break
save('finished_check_jobs')
