import subprocess as s,json,time
from pathlib import Path
w=Path('/Volumes/harddisk_5T/adele-workflow/products/grammys_2014/04_dark_horse/20261106')
p=json.load(open('concerts/grammys_2014/vertical_source.json'))['songs']['04_dark_horse']
t=time.monotonic()
with (w/'decode.log').open('w') as log:
 s.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','warning','-y','-i',p['source'],'-ss',str(p['slice'][0]),'-t',str(p['slice'][1]-p['slice'][0]),'-map','0:v:0','-map','0:a:0','-vf','bwdif=mode=send_field:parity=tff:deint=all,setsar=1','-r','50','-fps_mode','cfr','-c:v','libx264','-preset','ultrafast','-crf','0','-pix_fmt','yuv420p','-c:a','flac',str(w/'native50.mkv')],stdout=log,stderr=log,check=True)
(w/'prepare-timing.json').write_text(json.dumps({'stage':'source_decode_deinterlace_lossless','seconds':time.monotonic()-t,'source':p,'created':time.time()},indent=2))
print('PREPARED',time.monotonic()-t,flush=True)
