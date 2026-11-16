import subprocess as sp,numpy as np,json
from scipy.signal import correlate
p=json.load(open('concerts/grammys_2014/vertical_source.json'));ff='/opt/homebrew/bin/ffmpeg'
def audio(path,t,fast):
 cmd=[ff,'-v','error']+(['-ss',str(t)] if fast else [])+['-i',str(path)]+([] if fast else ['-ss',str(t)])+['-t','4','-vn','-ac','1','-ar','8000','-f','f32le','-']
 return np.frombuffer(sp.check_output(cmd,stderr=sp.DEVNULL),np.float32)
for n in ['01_drunk_in_love','05_does_anybody_really_know_what_ti']:
 row=p['songs'][n];a=audio(p['source'],row['slice'][0]+30,True);b=audio(row['directory']+'/source.mp4',30,True);size=min(len(a),len(b));a=a[:size];b=b[:size];r=correlate(a,b,method='fft');i=np.argmax(abs(r));print(n,float(r[i]/(np.linalg.norm(a)*np.linalg.norm(b))),int(i-(size-1)),flush=True)
