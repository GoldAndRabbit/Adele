"""Build one independently validated TS-derived release at a time."""
import argparse,json,os,shutil,subprocess,sys,tempfile,math
from pathlib import Path
from workflow.live.paths import Concert,read_json
from workflow.vertical_workflow import subtitle
from workflow.vertical_cover import header_labels
from workflow.portrait_validation import preview_problem
import pysubs2
ROOT=Path.cwd()
WD=ROOT/'work/grammy-ts60'
BASE=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014')
SOURCE=Path('/Volumes/harddisk_5T/thunder_downloads/The 56th Grammy Awards 2014.ts/The 56th Grammy Awards 2014.ts')
C=Concert('grammys_2014')
def ff(*args):
    subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y',*map(str,args)],check=True)
def run(name):
    song=C.dir/'songs'/name
    meta=read_json(song/'song.json')
    config=read_json(WD/'sync.json')[name]
    lead=config['lead']; start=config['offset']; dur=config['duration']
    edit=read_json(WD/'edit-plans.json',{}).get(name)
    if edit:
        start=edit['start']; dur=edit['end']-start
    elif any(b-a<=2 for a,b in zip(config['bad'],config['bad'][1:])):
        raise ValueError('Needs TS edit plan for neighbouring unmatched audio windows')
    d=BASE/'ts60-songs'/name; d.mkdir(exist_ok=True,parents=True)
    dest=song/'vertical/compare-ts-1080p60.mp4'
    output=d/'release-TS-1080p60.mp4'
    cp=subtitle(song)
    if edit:
        ass=pysubs2.load(str(cp)); events=[]
        for e in ass:
            left=e.start/1000-lead; right=e.end/1000-lead
            for low,high,offset in edit['segments']:
                a,b=max(left,low),min(right,high)
                if b-a<.08:continue
                n=e.copy(); n.start=round((a+offset-start+lead)*1000); n.end=round((b+offset-start+lead)*1000); events.append(n)
        ass.events=sorted(events,key=lambda e:e.start)
        cp=d/'captions.ass';ass.save(str(cp))
    native=d/'song50.mkv'; frames=round(dur*60)
    if not output.exists():
        if not native.exists():
            # Output seeking decodes the broadcast sequentially, including TS timestamp discontinuities.
            tmp=d/'pending50.mkv'
            ff('-i',SOURCE,'-ss',start,'-t',dur,'-map','0:v:0','-map','0:a:0','-vf','bwdif=mode=send_field:parity=tff:deint=all','-fps_mode','cfr','-r',50,'-c:v','libx264','-preset','ultrafast','-crf',0,'-c:a','flac',tmp)
            tmp.replace(native)
        chunks=[]
        for n in range(math.ceil(frames/300)):
            clip=d/f'segment{n:03}.mkv';chunks.append(clip)
            if clip.exists():continue
            count=min(300,frames-n*300)
            with tempfile.TemporaryDirectory() as folder:
                a,b=Path(folder)/'in',Path(folder)/'out';a.mkdir();b.mkdir()
                ff('-ss',n*5,'-i',native,'-vf','tpad=stop_mode=clone:stop_duration=0.12','-frames:v',max(2,round(count*5/6)+1),'-compression_level',1,a/'%08d.png')
                subprocess.run([ROOT/'bin/rife-ncnn-vulkan','-i',a,'-o',b,'-m',ROOT/'models/rife-v4.6','-n',str(count+1),'-j','2:3:2','-f','%08d.png'],check=True)
                if len(list(b.iterdir()))!=count+1:raise ValueError('Incomplete interpolation')
                ff('-framerate',60,'-i',b/'%08d.png','-frames:v',count,'-vf','scale=out_color_matrix=bt709','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-pix_fmt','yuv420p','-c:v','libx264','-crf',0,'-preset','ultrafast',d/'pending.mkv')
                (d/'pending.mkv').replace(clip)
            print(name,'RIFE',n+1,'/',math.ceil(frames/300),flush=True)
        concat=d/'concat.txt';concat.write_text(''.join(f"file '{p.name}'\n" for p in chunks))
        clean=d/'song60.mkv'
        ff('-f','concat','-safe',0,'-i',concat,'-i',native,'-map','0:v','-map','1:a','-c','copy',clean)
        label=header_labels(C,meta);title=read_json(song/'post_draft.json',{}).get('song',{}).get('title_song') or meta['title']
        tmp=d/'pending.mp4';tmp.unlink(missing_ok=True)
        subprocess.run([sys.executable,'-m','workflow.vertical',clean,tmp,'--fps','60','--song-directory',song,'--song',title,'--en',label['en'],'--zh',label['zh'],'--intro',label['event'],'--captions',cp,'--start','0','--caption-start',str(lead),'--duration',str(dur)],check=True)
        tmp.replace(output)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',output]))
    v=next(s for s in info['streams'] if s['codec_type']=='video');a=next(s for s in info['streams'] if s['codec_type']=='audio')
    if (v['width'],v['height'],v['avg_frame_rate'])!=(1080,1920,'60/1') or max(abs(float(s['duration'])-dur) for s in (v,a))>.10:raise ValueError('AV validation failed')
    from verify_clock import verify_audio_clock
    verify_audio_clock(output,start,dur)
    problem=preview_problem(C,meta,output)
    if problem:raise ValueError(problem)
    tmp=dest.with_suffix('.pending');tmp.unlink(missing_ok=True);tmp.symlink_to(output);tmp.replace(dest)
    # Only this worker's intermediate chunks are disposable, and only after the completed file is verified.
    for p in d.glob('segment[0-9][0-9][0-9].mkv'):p.unlink()
    print('READY',name,dest,flush=True)
if __name__=='__main__':
    held = {"03_invisible", "05_does_anybody_really_know_what_ti", "09_try_just_give_me_a_reason", "17_one"}
    if sys.argv[1] in held:
        print("HOLD: broadcast edit waiting for user review", flush=True)
        sys.exit(75)
    run(sys.argv[1])
