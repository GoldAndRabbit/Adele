"""Prepare complete clean source clips for browser portrait review, without burning overlays."""
import fcntl,json,subprocess,tempfile
from pathlib import Path
from workflow.live.paths import read_json,write_json
from workflow.vertical_cover import original_source,cover_ffmpeg

BASE=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews')

def source_identity(source, span, audio_decoder=None):
 identity={'source':str(source.resolve()),'mtime':source.stat().st_mtime_ns,'slice':span}
 if audio_decoder:identity['audio_decoder']=audio_decoder
 return identity

def probe(path):
 return json.loads(subprocess.check_output([str(Path(cover_ffmpeg()).with_name('ffprobe')),'-v','error','-show_streams','-show_format','-of','json',str(path)]))

def prepare_preview_crop(directory, clip):
    from workflow.letterbox import detect
    marker = directory / 'vertical' / 'preview_crop.json'
    stat = clip.stat()
    identity = {'clip': str(clip.resolve()), 'mtime_ns': stat.st_mtime_ns, 'size': stat.st_size}
    if read_json(marker, {}).get('input') != identity:
        box = detect(clip, independent_edges=True)
        marker.parent.mkdir(exist_ok=True)
        write_json(marker, {'input': identity, 'box': box})


def prepare_browser(concert,item,*,native_playback_verified=False):
 d=concert.song_dir(item);info=read_json(d/'song.json',{})
 seg=next((x for x in (concert.load('segments') or {}).get('items',[]) if x['name']==item['name']),{})
 selected=read_json(concert.dir/'vertical_source.json',{}).get('songs',{}).get(item['name'])
 span=(selected or {}).get('slice') or info.get('slice') or [seg.get('start'),seg.get('end')]
 if any(x is None for x in span):raise ValueError('缺少已确认曲目范围')
 a,b=span;source=original_source(concert,item).resolve();meta=probe(source)
 video=next(x for x in meta['streams'] if x['codec_type']=='video');audio=next(x for x in meta['streams'] if x['codec_type']=='audio')
 duration=float(meta['format']['duration'])
 if a<0 or b<=a or b>duration+.25:raise ValueError(f'曲目范围 {span} 超出原片时长 {duration}')
 folder=Path(selected['directory']) if selected else BASE/concert.slug/'browser-sources'/item['name'];folder.mkdir(parents=True,exist_ok=True)
 audio_decoder=(selected or {}).get('audio_decoder') or concert.load('info',{}).get('audio_decoder')
 out=folder/'source.mp4';marker=folder/'source.json';identity=source_identity(source,span,audio_decoder)
 if not out.is_file() or read_json(marker)!=identity:
  if a<.05 and abs(b-duration)<.25 and source.suffix.lower()=='.mp4' and (native_playback_verified or (video['height']<=1080 and video['codec_name']=='h264' and audio['codec_name']=='aac')):
   tmp=folder/'source.pending';tmp.unlink(missing_ok=True);tmp.symlink_to(source);tmp.replace(out)
  else:
   with tempfile.TemporaryDirectory(dir=folder) as temp:
    pending=Path(temp)/'source.mp4'
    filters=[]
    if video.get('field_order') in ('tt','bb','tb','bt'):filters.append('bwdif=mode='+('send_field' if (selected or {}).get('kind')=='ts' else 'send_frame')+':parity=auto:deint=all')
    if video.get('color_transfer') in ('arib-std-b67', 'smpte2084') and video.get('color_primaries') == 'bt2020':
     # zimg cannot linearize constant-luminance HLG directly. Decode using
     # the supported BT.2020 matrix before mapping HDR to browser SDR.
     resize = 'w=-2:h=1080:' if video['height'] > 1080 else ''
     matrix = 'min=bt2020nc:' if video.get('color_space') == 'bt2020c' else ''
     filters.extend([f'zscale={matrix}{resize}t=linear:npl=100', 'format=gbrpf32le',
                     'zscale=p=bt709', 'tonemap=mobius', 'zscale=t=bt709:m=bt709:r=limited', 'format=yuv420p'])
    elif video['height']>1080:filters.append('scale=-2:1080')
    subprocess.run([cover_ffmpeg(),'-nostdin','-v','error','-ss',str(a),*(['-c:a',audio_decoder] if audio_decoder else []),'-i',str(source),'-t',str(b-a),'-map','0:v:0','-map','0:a:0',*(['-vf',','.join(filters)] if filters else []),'-c:v','h264_videotoolbox','-a53cc','0','-b:v','10M','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-movflags','+faststart',str(pending)],check=True)
    check=probe(pending)
    if abs(float(check['format']['duration'])-(b-a))>.25:raise ValueError('原片切片时长不符')
    pending.replace(out)
  write_json(marker,identity)
 prepare_preview_crop(d,out)
 for link in [d/'preview.mp4',d/'vertical/original-selected.mp4']:
  link.parent.mkdir(exist_ok=True);tmp=link.with_name(link.name+'.browser-pending');tmp.unlink(missing_ok=True);tmp.symlink_to(out);tmp.replace(link)
 info.update(slice=span,preview=span,preview_mode='browser',source_file=str(source),source_kind='original',source_review='pending');write_json(d/'song.json',info)
 with (concert.dir/'.browser-policy.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  policy=read_json(concert.dir/'vertical_source.json',{'source':str(source),'songs':{}})
  policy['songs'][item['name']]=selected or {'source':str(source),'kind':'original','slice':span,'directory':str(folder)};write_json(concert.dir/'vertical_source.json',policy)
  if audio_decoder:
   policy['songs'][item['name']]['audio_decoder']=audio_decoder;write_json(concert.dir/'vertical_source.json',policy)
  previews=read_json(concert.dir/'browser_previews.json',{'songs':[]});previews['songs']=list(dict.fromkeys([*previews['songs'],item['name']]));write_json(concert.dir/'browser_previews.json',previews)
 return out
