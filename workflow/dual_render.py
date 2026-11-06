"""Shared dual-platform compositor; encoding uses the existing song render preset."""
from pathlib import Path
import json,subprocess as sp,time,math,hashlib,fcntl
import pysubs2
from PIL import Image,ImageDraw,ImageFont
from workflow.live.paths import Concert
from workflow.vertical_workflow import first_lyric,subtitle
from workflow.portrait_header import draw_portrait_header,STYLE,PINGFANG
from workflow.portrait_browser import preview_data
from workflow.song.render import DEFAULT_ENCODER, ENCODERS
R=Path(__file__).resolve().parents[1]
def configure(concert, item, output):
 global W,C,D,START,DURATION,ITEM
 C=concert;ITEM=item;D=C.song_dir(item);W=Path(output)
 policy=json.loads((C.dir/'vertical_source.json').read_text())['songs'][item['name']]
 START=max(0,first_lyric(D)-.5);DURATION=policy['slice'][1]-policy['slice'][0]-START
FF=['/opt/homebrew/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','warning','-y'];FONT='/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf'
def save(p,v):
 tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2));tmp.replace(p)
def timing(stage,seconds,**kw):
 p=W/'timings.json'
 with (W/'timings.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  v=json.loads(p.read_text()) if p.exists() else [];v.append({'stage':stage,'seconds':seconds,**kw});save(p,v)
def assets():
 t=time.monotonic();out=pysubs2.SSAFile();src=pysubs2.load(str(subtitle(D)))
 data=preview_data(C,ITEM,D);labels=data['header_text']
 image=Image.new('RGBA',(1080,1920));draw_portrait_header(image,labels['song'],labels['en'],'',labels['event'],True,song_zh=labels['song_zh']);image.save(W/'header.png')
 for kind,width,height,fade in [('portrait',1080,608,56),('landscape',3840,2054,44)]:
  mask=Image.new('L',(width,height),255);draw=ImageDraw.Draw(mask)
  for y in range(height-fade,height):draw.line((0,y,width,y),fill=round(255*(height-1-y)/fade))
  mask.save(W/f'{kind}-mask.png')
 for kind in ['portrait','landscape']:
  out=pysubs2.SSAFile();out.info.update(PlayResX=str(1080 if kind=='portrait' else 3840),PlayResY=str(1920 if kind=='portrait' else 2160),WrapStyle='2',ScaledBorderAndShadow='yes')
  specs={'EN':(36,8,1344),'ZH':(72,8,1272),'Note':(38,8,670)} if kind=='portrait' else {'EN':(120,2,154),'ZH':(120,8,2010),'Note':(96,8,24)}
  for key,(size,align,y) in specs.items():
   out.styles[key]=pysubs2.SSAStyle(fontname=STYLE['english_font'] if key=='EN' else STYLE['chinese_font'],fontsize=size,alignment=align,marginl=72,marginr=72,marginv=y,primarycolor=pysubs2.Color(204,255,0) if key=='Note' else pysubs2.Color(255,255,255),outline=0 if key=='Note' else (4 if kind=='portrait' else 6),shadow=0)
  for e in src:
   if e.is_comment or e.end<=START*1000:continue
   rows=e.plaintext.splitlines()
   if not rows or rows[0].startswith('《'):continue
   if e.style=='Note':texts=[('Note',' '.join(rows))]
   else:texts=[('EN',rows[0]),('ZH',' '.join(rows[1:]).strip(' ♪♫♬🎵🎶'))]
   if kind=='portrait' and e.style!='Note':
    en=rows[0];zh=' '.join(rows[1:]).strip(' ♪♫♬🎵🎶')
    text=(r'{\q0\fn'+STYLE['chinese_font']+r'\fs72}'+zh+r'\N' if zh else '')+r'{\fn'+STYLE['english_font']+r'\fs36}'+en
    out.events.append(pysubs2.SSAEvent(start=max(0,e.start-round(START*1000)),end=e.end-round(START*1000),style='ZH',text=text))
    continue
   for key,text in texts:
    if not text:continue
    size=specs[key][0];size_override=''
    if kind=='landscape' and key!='Note':
     font=ImageFont.truetype(FONT if key=='EN' else str(PINGFANG),size)
     measured=font.getlength(text)/(1.157 if key=='EN' else 1.4)
     fitted=min(size,size*3696/max(1,measured));size_override=r'{\fs'+str(round(fitted,2))+'}'
    # Match preview's larger Chinese followed by smaller English, allowing long Chinese to wrap.
    if kind=='portrait' and key=='ZH':
     text=r'{\q0}'+text
    out.events.append(pysubs2.SSAEvent(start=max(0,e.start-round(START*1000)),end=e.end-round(START*1000),style=key,text=size_override+text))
  out.save(str(W/f'{kind}.ass'))
 timing('prepare_titles_subtitles_masks',time.monotonic()-t)
def graph(kind):
 # The main video frame stays proportional; all overlays are added after interpolation.
 if kind=='portrait':
  g='[0:v]split=3[c][u][l];[c]scale=1080:608:flags=lanczos,format=rgb24[c0];[c0][2:v]alphamerge[cs];'
  g+='[u]crop=iw:ih/2:0:0,scale=270:240:force_original_aspect_ratio=increase,crop=270:240,gblur=sigma=12,scale=1080:960[ub];'
  g+='[l]crop=iw:ih*.3:0:ih-oh,scale=270:240:force_original_aspect_ratio=increase,crop=270:240,gblur=sigma=28,scale=1080:960[lb];'
  g+='[ub][lb]vstack[bg];[bg][cs]overlay=0:656:shortest=1[bgc];[bgc][1:v]overlay=0:0:shortest=1[base];'
  x,y,vw,vh=0,656,1080,608
 else:
  g='[0:v]split=3[c][bg][edge];[c]scale=3840:2160:flags=lanczos,crop=3840:2054:0:53,format=rgb24[c0];[c0][2:v]alphamerge[cs];'
  g+='[bg]scale=384:216,gblur=sigma=12,scale=3840:2160[bg0];'
  g+='[edge]crop=iw:ih*.035:0:ih-oh-26,scale=480:20,gblur=sigma=8,scale=3840:150[edge0];'
  g+='[bg0][edge0]overlay=0:2010:shortest=1[bg1];[bg1][cs]overlay=0:0:shortest=1[base];'
  x,y,vw,vh=0,-53,3840,2160
 plan=json.loads((D/'watermark.json').read_text());items=[i for i in plan['items'] if i['t']+i['dur']>START]
 if items:
  g+='[3:v]split='+str(len(items))+''.join(f'[logo{i}]' for i in range(len(items)))+';'
  last='base'
  for i,item in enumerate(items):
   st=item['t']-START;end=st+item['dur'];fade=item['fade'];width=round(vw*plan['width'])
   g+=f"[logo{i}]scale={width}:-1,format=rgba,colorchannelmixer=aa={plan['opacity']},fade=t=in:st={st}:d={fade}:alpha=1,fade=t=out:st={end-fade}:d={fade}:alpha=1[wm{i}];"
   g+=f"[{last}][wm{i}]overlay=x={x+vw*item['x']}:y={y+vh*item['y']}:shortest=1:enable='between(t,{st},{end})'[marked{i}];";last=f'marked{i}'
 else:last='base'
 g+=f"[{last}]ass=filename='{W/kind}.ass':fontsdir='{PINGFANG.parent}',format=yuv420p,setsar=1[out]"
 return g

def render(kind,sample=False,commit=True,timing_metadata=None):
 t=time.monotonic();name='bilibili-4k60' if kind=='landscape' else 'douyin-1080p60';dest=W/(name+('-sample' if sample else '')+'.mp4');pending=dest.with_suffix('.pending.mp4')
 inputs=['-ss',str(START),'-i',str(W/('native50.mkv' if sample else 'master60.mkv')),'-loop','1','-framerate','60','-i',str(W/'header.png'),'-loop','1','-framerate','60','-i',str(W/f'{kind}-mask.png'),'-loop','1','-framerate','60','-i',str(R/'assets/adele-logo.png')]
 cmd=FF+inputs+['-filter_complex_threads','4','-filter_complex',graph(kind),'-map','[out]','-map','0:a:0','-t',str(3 if sample else DURATION),'-r','60','-fps_mode','cfr',*ENCODERS[DEFAULT_ENCODER],'-pix_fmt','yuv420p','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-color_range','tv','-c:a','aac','-ac','2','-ar','48000','-b:a','320k','-movflags','+faststart','-progress',str(W/f'{name}.progress'),str(pending)]
 with (W/f'{name}.log').open('w') as log:sp.run(cmd,stdout=log,stderr=log,check=True)
 if commit:pending.replace(dest)
 seconds=time.monotonic()-t;timing(name+('_sample' if sample else '_render_encode'),seconds,output=str(dest),duration=3 if sample else DURATION,**(timing_metadata or {}))
 print('READY',kind,seconds,flush=True)
 return dest if commit else pending
