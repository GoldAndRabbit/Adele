"""Recover the missing preview audio from the original full-show audio track."""
import subprocess
import tempfile
import sys
from pathlib import Path
from workflow.live.paths import Concert
from workflow.subtitle_metadata_batch import ensure_audio

c = Concert('chappell_lolla_brasil_2026')
item = c.item('03_after_midnight')
d = c.song_dir(item)
policy = c.load('vertical_source')['songs'][item['name']]
start,end = policy['slice']
clip = Path(policy['directory'])/'source.mp4'
with tempfile.TemporaryDirectory(dir=clip.parent) as tmp:
    audio = Path(tmp)/'audio.flac'
    out = Path(tmp)/'preview.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-c:a','eac3_at','-i',policy['source'],'-ss',str(start),'-t',str(end-start),'-map','0:a:0','-ac','2','-ar','48000',str(audio)],check=True)
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',audio]))
    if abs(duration-(end-start))>.25:
        raise ValueError(f'音轨时长异常 {duration}')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',clip,'-i',audio,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','256k','-movflags','+faststart',out],check=True)
    out.replace(clip)
ensure_audio(c,item)
subprocess.run([sys.executable,'-u','-m','workflow.song.run','song',c.slug,item['name']],check=True)
