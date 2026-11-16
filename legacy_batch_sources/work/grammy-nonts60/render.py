import json,os,subprocess as sp,tempfile
from pathlib import Path
root=Path.cwd()
work=root/'work/grammy-nonts60'
songs=root/'posts/grammys_2014'
base=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/non-ts-60')
base.mkdir(exist_ok=True)
names=['01_drunk_in_love','02_royals','04_dark_horse']
def streams(file):
    return json.loads(sp.check_output(['ffprobe','-v','error','-show_streams','-of','json',file]))['streams']
def audio_hash(file):
    return sp.check_output(['ffmpeg','-v','error','-i',file,'-map','0:a:0','-c','copy','-f','hash','-hash','sha256','-'])
def render(name):
    folder=songs/name/'vertical'
    old=folder/json.loads((folder/'release.json').read_text())['file']
    orig=next(s for s in streams(old) if s['codec_type']=='video')
    assert (orig['width'],orig['height'],orig['avg_frame_rate'])==(1080,1920,'30/1')
    dest=base/(name+'-'+old.stem+'-60fps.mp4')
    if not dest.exists():
        tmp=dest.with_suffix('.pending.mp4')
        ff=['ffmpeg','-nostdin','-v','error','-y']
        with sp.Popen(ff+['-i',old,'-map','0:v:0','-fps_mode','passthrough','-pix_fmt','nv12','-f','rawvideo','-'],stdout=sp.PIPE) as dec, sp.Popen([work/'midpoint'],stdin=dec.stdout,stdout=sp.PIPE) as interp:
            dec.stdout.close()
            color=[]
            for attr,opt in [('color_space','-colorspace'),('color_transfer','-color_trc'),('color_primaries','-color_primaries'),('color_range','-color_range')]:
                if orig.get(attr) not in (None,'unknown'):color.extend([opt,orig[attr]])
            with sp.Popen(ff+['-framerate','60','-video_size','1080x1920','-pixel_format','nv12','-f','rawvideo','-i','-','-i',old,'-map','0:v','-map','1:a:0','-c:v','libx264','-preset','veryfast','-crf','17','-pix_fmt','yuv420p',*color,'-c:a','copy','-movflags','+faststart',tmp],stdin=interp.stdout) as enc:
                interp.stdout.close()
                codes=(enc.wait(),interp.wait(),dec.wait())
                if any(codes):raise RuntimeError(f'Encoding failed {codes}')
        v=next(s for s in streams(tmp) if s['codec_type']=='video')
        assert (v['width'],v['height'],v['avg_frame_rate'],int(v['nb_frames']))==(1080,1920,'60/1',2*int(orig['nb_frames']))
        assert abs(float(v['duration'])-float(orig['duration']))<.02 and audio_hash(tmp)==audio_hash(old)
        tmp.replace(dest)
    link=folder/'compare-nonts-1080p60.mp4'; pending=link.with_suffix('.pending');pending.unlink(missing_ok=True);pending.symlink_to(dest);pending.replace(link)
    print('READY',name,str(dest),flush=True)
for name in names:
    print('START',name,flush=True)
    try: render(name)
    except Exception as exc:print('FAILED',name,repr(exc),flush=True)
