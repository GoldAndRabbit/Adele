"""Build the three complete performances where the TS broadcast omitted sung passages."""
from render import BASE, C, ROOT, SOURCE, WD, ff
from verify_clock import verify_audio_clock
from workflow.live.paths import read_json
from workflow.vertical_workflow import subtitle
from workflow.vertical_cover import header_labels
from workflow.portrait_validation import preview_problem
from pathlib import Path
import json, math, subprocess as sp, sys, tempfile
import numpy as np
from scipy.signal import correlate

# Times are on the same trimmed song clock as the original reviewed release.
CUTS={
    '03_invisible':[(0,1245.028),(5.9,None),(39.1,1228.324)],
    '09_try_just_give_me_a_reason':[(0,None),(38.2,3378.811)],
    '17_one':[(0,7373.728),(79.3,None),(114.95,7341.696),(240.5,None),(244.2,7338.848)],
}
def near(path,t):
    return np.frombuffer(sp.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',path,'-t','1.5','-vn','-ac','1','-ar','8000','-f','s16le','-']),'<i2').astype(float)
def render(name):
    rec=read_json(WD/'sync.json')[name];dur=rec['duration'];lead=rec['lead'];old=Path(C.load('info')['source_file'])
    dir=BASE/'ts60-songs'/name;dir.mkdir(exist_ok=True,parents=True)
    song=C.dir/'songs'/name;meta=read_json(song/'song.json')
    spans=CUTS[name]+[(dur,None)]
    paths=[];total_frames=round(dur*60);report=[]
    for ix,((left,offset),(right,_)) in enumerate(zip(spans,spans[1:])):
        first=round(left*60);stop=round(right*60);count=stop-first
        left=first/60;length=count/60;source_start=(rec['begin'] if offset is None else offset)+left
        part=dir/f'part{ix:02}.mkv';paths.append(part)
        report.append(dict(start=left,end=(first+count)/60,source='original_720p' if offset is None else '56th_TS',source_start=source_start))
        if part.exists():continue
        native=dir/f'part{ix:02}-native.mkv'
        fps=30000/1001 if offset is None else 50
        if not native.exists():
            out=dir/'part-pending-native.mkv'
            if offset is None:
                ff('-ss',source_start,'-i',old,'-t',length+.10,'-map','0:v:0','-map','0:a:0',
                   '-vf','scale=1920:1080:flags=lanczos,setsar=1','-pix_fmt','yuv420p','-c:v','libx264','-crf',0,'-preset','ultrafast','-ar',48000,'-ac',2,'-c:a','flac',out)
            else:
                ff('-i',SOURCE,'-ss',source_start,'-t',length+.1,'-map','0:v:0','-map','0:a:0',
                   '-vf','bwdif=mode=send_field:parity=tff:deint=all','-r',50,'-fps_mode','cfr','-c:v','libx264','-crf',0,'-preset','ultrafast','-ar',48000,'-ac',2,'-c:a','flac',out)
            out.replace(native)
        clips=[]
        for k in range(math.ceil(count/300)):
            n=min(count-k*300,300);clip=dir/f'h{ix:02}-{k:03}.mkv';clips.append(clip)
            if clip.exists():continue
            with tempfile.TemporaryDirectory() as t:
                a,b=Path(t)/'a',Path(t)/'b';a.mkdir();b.mkdir()
                ff('-ss',k*5,'-i',native,'-vf','tpad=stop_mode=clone:stop_duration=0.15','-frames:v',max(2,round(n/60*fps)+1),'-compression_level',1,a/'%08d.png')
                sp.run([ROOT/'bin/rife-ncnn-vulkan','-i',a,'-o',b,'-m',ROOT/'models/rife-v4.6','-n',str(n+1),'-j','2:3:2','-f','%08d.png'],check=True)
                if len(list(b.iterdir()))!=n+1: raise ValueError('Incomplete RIFE segment')
                ff('-framerate',60,'-i',b/'%08d.png','-frames:v',n,'-vf','scale=out_color_matrix=bt709','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-pix_fmt','yuv420p','-c:v','libx264','-crf',0,'-preset','ultrafast',dir/'pending.mkv')
                (dir/'pending.mkv').replace(clip)
            print(name,ix,k+1,'/',len(range(math.ceil(count/300))),flush=True)
        listing=dir/'chunks.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in clips))
        ff('-f','concat','-safe',0,'-i',listing,'-i',native,'-map','0:v','-map','1:a','-c:v','copy','-af',f'atrim=end_sample={count*800},asetpts=PTS-STARTPTS','-c:a','flac',dir/'part-pending.mkv')
        (dir/'part-pending.mkv').replace(part)
    manifest=dir/'source-map.json';manifest.write_text(json.dumps(report,indent=2))
    listing=dir/'parts.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in paths))
    clean=dir/'song60.mkv'
    ff('-f','concat','-safe',0,'-i',listing,'-c','copy',clean)
    labels=header_labels(C,meta);title=read_json(song/'post_draft.json',{}).get('song',{}).get('title_song') or meta['title']
    tmp=dir/'pending.mp4';tmp.unlink(missing_ok=True)
    sp.run([sys.executable,'-m','workflow.vertical',clean,tmp,'--fps','60','--song-directory',song,'--song',title,'--en',labels['en'],'--zh',labels['zh'],'--intro',labels['event'],'--captions',subtitle(song),'--start','0','--caption-start',str(lead),'--duration',str(dur)],check=True)
    streams=json.loads(sp.check_output(['ffprobe','-v','error','-show_streams','-of','json',tmp]))['streams']
    v=next(s for s in streams if s['codec_type']=='video');aud=next(s for s in streams if s['codec_type']=='audio')
    if (v['width'],v['height'],v['avg_frame_rate'])!=(1080,1920,'60/1') or any(abs(float(s['duration'])-dur)>.10 for s in (aud,v)):raise ValueError('hybrid format/duration mismatch')
    # Check both sides of each source change against the reviewed audio timeline.
    for r in report:
        for t in (r['start']+.5,(r['start']+r['end'])/2,r['end']-2):
            if t<r['start'] or t+1.5>r['end']:continue
            y=near(tmp,t);x=near(old,rec['begin']+t)
            z=correlate(x,y,mode='full',method='fft')/max(np.linalg.norm(x)*np.linalg.norm(y),1e-9)
            mid=len(y)-1;l=z[mid-640:mid+641];best=int(np.argmax(abs(l)))
            if abs(l[best])<.22 or abs(best-640)>520:raise ValueError(f'{name} audio alignment at {t:.2f}: {l[best]:.3f}; {best-640} samples')
    problem=preview_problem(C,meta,tmp)
    if problem:raise ValueError(problem)
    output=dir/'release-TS-1080p60.mp4';tmp.replace(output)
    dest=song/'vertical/compare-ts-1080p60.mp4';link=dest.with_suffix('.pending');link.unlink(missing_ok=True);link.symlink_to(output);link.replace(dest)
    for path in dir.glob('h[0-9][0-9]-[0-9][0-9][0-9].mkv'):path.unlink()
    print('READY',name,flush=True)
