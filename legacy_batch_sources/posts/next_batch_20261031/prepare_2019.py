import subprocess,pathlib,json,os,time
b=pathlib.Path(__file__).parent
p='.venv/bin/python'
s={'pid':os.getpid(),'stage':'references','started':time.time()}
def save(stage):
 s['stage']=stage;(b/'prepare_2019_status.json').write_text(json.dumps(s,indent=2))
try:
 save('references')
 subprocess.run([p,str(b/'fetch_2019_references.py')],check=True)
 assert pathlib.Path('posts/next_20261031_ziwkheqvq4s/lyrics.txt').exists(),'Reference pool incomplete'
 save('download_and_precision')
 subprocess.run([p,'-u',str(b/'run.py'),'--prepare-now','--only','next_20261031_ziwkheqvq4s'],check=True)
 save('pipeline_returned_check_job_status')
except Exception as e:
 s['error']=str(e);save('blocked')
