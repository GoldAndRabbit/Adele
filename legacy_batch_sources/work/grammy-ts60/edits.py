exec(open('work/grammy-ts60/sync.py').read().split('records={}')[0])
for name,band in [('03_invisible',45),('09_try_just_give_me_a_reason',45),('17_one',60),('05_does_anybody_really_know_what_ti',45)]:
 rec=json.loads((wd/'sync.json').read_text())[name]; dur=rec['duration']; off=rec['offset']; old=np.frombuffer(sp.check_output(['ffmpeg','-v','error','-ss',str(rec['begin']),'-i',c.load('info')['source_file'],'-t',str(dur),'-vn','-ar','8000','-ac','1','-f','s16le','-']),'<i2').astype(float)/32768
 rows=[]
 for t in np.arange(0,int(dur)-1,.5):
    y=old[int(t*8000):int((t+1)*8000)]; start=round((off+t-band)*8000); x=ts[start:start+len(y)+band*16000].astype(float)/32768
    z=signal.correlate(x,y,mode='valid',method='fft');pw=np.r_[0.,np.cumsum(x*x)];z/=np.sqrt(np.maximum((pw[len(y):]-pw[:-len(y)])*(y*y).sum(),1e-10)); k=abs(z).argmax();rows.append([t,round((start+k)/8000-t,3),round(abs(z[k]),3)])
 (wd/(name+'.matches.json')).write_text(json.dumps(rows))
 print(name,flush=True)
