from pathlib import Path
import subprocess as sp
from concurrent.futures import ThreadPoolExecutor
S=Path('/Volumes/harddisk_5T/thunder_downloads/The 56th Grammy Awards 2014.ts/The 56th Grammy Awards 2014.ts')
D=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/ts-reviews');D.mkdir(exist_ok=True)
bounds={'03_invisible':(1242.86,1443.664),'09_try_just_give_me_a_reason':(3415.5,3719.692),'05_does_anybody_really_know_what_ti':(2015.4612,2267.8712),'17_one':(7284.488,7620.108)}
def extract(item):
 n,(a,b)=item;d=D/n;d.mkdir(exist_ok=True);out=d/'source.mp4';tmp=d/'extracting.mp4'
 if out.exists():return
 sp.run(['ffmpeg','-nostdin','-v','error','-y','-i',S,'-ss',str(a),'-t',str(b-a),'-map','0:v:0','-map','0:a:0','-vf','bwdif=mode=send_field:parity=tff:deint=all','-r','50','-c:v','libx264','-preset','veryfast','-crf','16','-c:a','aac','-b:a','320k','-movflags','+faststart',tmp],check=True)
 tmp.replace(out);print('CLEAN',n,flush=True)
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(extract,bounds.items()))
