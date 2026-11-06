/* One decoder drives the clear picture and both blurred regions. */
function browserPortrait(data) {
  const video = h('video', {src:data.url, playsinline:true, preload:'metadata', class:'browser-portrait-source', 'aria-hidden':'true'});
  const canvas = h('canvas', {width:540, height:960, 'aria-label':'实时竖屏预览'});
  const ctx = canvas.getContext('2d');
  const scratch = document.createElement('canvas'); scratch.width=135; scratch.height=120;
  const bg = scratch.getContext('2d');
  const picture=document.createElement('canvas');
  const pictureCtx=picture.getContext('2d');
  const mark = new Image();mark.src='adele-logo.png';
  const play = h('button', {class:'btn mini', 'aria-label':'横竖同步播放'}, '同步播放');
  const seek = h('input', {type:'range',min:0,max:1,step:.01,value:0,'aria-label':'实时预览进度'});
  const clock = h('small', {}, '0:00');
  const mute = h('button', {class:'btn mini','aria-label':'静音实时预览'}, '静音');
  const fullscreen = h('button', {class:'btn mini'}, '全屏');
  const stage = h('div', {class:'browser-portrait-stage'}, canvas, video);
  const controls = h('div', {class:'browser-portrait-controls'},play,clock,mute,fullscreen,seek);
  const display = h('div', {class:'browser-portrait-display'},stage,controls);
  const el = h('div', {class:'pane portrait-player browser-portrait'},display,
    h('small', {}, '实时预览 · 原片播放 / 标题和字幕动态叠加'),formatLabel(data.format));
  let frame=0, decodedFrame=0, disposed=false;
  const captions=(data.captions||[]).filter(e=>e.style!=='Note' && !e.orig.startsWith('《'));
  // Use the exact same DOM renderer, font metrics and black stroke as horizontal subtitles.
  const settings=data.style;
  const style={size:settings.english_size,color:settings.subtitle_color,outline:settings.subtitle_outline,marginL:72,marginR:72,marginV:settings.subtitle_y,align:8,box:null};
  const captionAss={playResX:1080,playResY:1920,styles:{Default:style,Note:{size:38,color:'#CCFF00',outline:0,marginL:36,marginR:36,marginV:670,align:8,box:null}},events:[]};
  const subtitleRenderer=new SubRenderer(stage,captionAss);
  const events=captions.map(cue=>({start:cue.start,end:cue.end,style:'Default',lines:[
    {text:(cue.zh||'').replace(/[♪♫♬🎵🎶]/gu,'').trim(),size:settings.chinese_size},
    {text:cue.orig,size:settings.english_size}
  ]}));
  events.push(...previewNotes(data));
  const headerLines=[];
  for(const [key,y,size,color] of settings.header) {
    let label=data.header_text?.[key]||'';
    if(key==='en')label=label.toUpperCase();
    const family=SUB_FONTS[(key==='zh'||key==='song_zh'||key==='event')?'cjk':'latin'].family;
    const line=h('div',{class:'browser-portrait-title', 'data-field':key},label);
    Object.assign(line.style,{top:`${y/1920*100}%`,fontFamily:family,color});
    stage.append(line);headerLines.push({line,key,size,family,label,max:key==='song'?1000:960});
  }
  function layoutText() {
    const scale=stage.clientWidth/1080;
    for(const item of headerLines) {
      ctx.font=`${item.size}px ${item.family}`;
      const fitted=item.size*Math.min(1,item.max/Math.max(1,ctx.measureText(item.label).width));
      item.line.style.fontSize=`${fitted*scale}px`;
      item.line.style.webkitTextStroke=`${2*(item.key === "song" ? settings.title_outline : settings.header_outline)*scale}px #000`;
    }
    subtitleRenderer.layout(stage.clientWidth,stage.clientHeight,9/16);
  }
  const resize=new ResizeObserver(layoutText);resize.observe(stage);
  function draw() {
    if(disposed)return;
    ctx.fillStyle='#000';ctx.fillRect(0,0,540,960);
    if(video.readyState>=2 && video.videoWidth) {
      const box=data.box||{x:0,y:0,w:1,h:1};
      const sx=video.videoWidth*box.x, sy=video.videoHeight*box.y;
      const sw=video.videoWidth*box.w, sh=video.videoHeight*box.h;
      function blur(y,height,dest,amount) {
        // Cover the small buffer using the selected upper/lower source strip.
        const ratio=Math.max(135/sw,120/height),w=sw*ratio,hh=height*ratio;
        bg.filter='none';bg.drawImage(video,sx,y,sw,height,(135-w)/2,(120-hh)/2,w,hh);
        ctx.save();ctx.beginPath();ctx.rect(0,dest,540,480);ctx.clip();ctx.filter=`blur(${amount}px)`;
        ctx.drawImage(scratch,-35,dest-35,610,550);ctx.restore();
      }
      blur(sy,sh/2,0,24);blur(sy+sh*.7,sh*.3,480,56);
      const height=540*video.videoHeight/video.videoWidth;
      if(data.portrait_soft_lower_edge) {
        const ph=Math.round(height);
        if(picture.width!==540||picture.height!==ph){picture.width=540;picture.height=ph;}
        pictureCtx.clearRect(0,0,540,ph);
        pictureCtx.drawImage(video,sx,sy,sw,sh,0,0,540,ph);
        // Feather only the lower picture edge into the blurred video background.
        const fade=pictureCtx.createLinearGradient(0,ph-28,0,ph);
        fade.addColorStop(0,'#fff');fade.addColorStop(1,'transparent');
        pictureCtx.globalCompositeOperation='destination-in';
        pictureCtx.fillStyle=fade;pictureCtx.fillRect(0,0,540,ph);
        pictureCtx.globalCompositeOperation='source-over';
        ctx.drawImage(picture,0,(960-height)/2,540,height);
      } else ctx.drawImage(video,sx,sy,sw,sh,0,(960-height)/2,540,height);
      const plan=data.watermark, t=video.currentTime+(data.start||0);
      if(plan && mark.complete && mark.naturalWidth) for(const item of plan.items||[]) {
        if(t<item.t || t>=item.t+item.dur)continue;
        const fade=Math.max(.001,item.fade||0), alpha=Math.min(1,(t-item.t)/fade,(item.t+item.dur-t)/fade);
        const width=540*plan.width;
        ctx.save();ctx.globalAlpha=(plan.opacity??.6)*Math.max(0,alpha);
        ctx.drawImage(mark,540*item.x,(960-height)/2+height*item.y,width,width*mark.naturalHeight/mark.naturalWidth);ctx.restore();
      }
    }
    const time=video.currentTime+(data.start||0);
    subtitleRenderer.render(events.filter(cue=>cue.start<=time && time<cue.end));
    seek.value=video.currentTime;clock.textContent=fmt(time);
  }
  function tick(){draw();if(!video.paused&&!video.ended&&!disposed)frame=requestAnimationFrame(tick);}
  function toggle(){if(video.paused)video.play().catch(e=>{if(e.name!=="AbortError")toast(e.message,false);});else video.pause();}
  play.addEventListener('click',toggle);canvas.addEventListener('click',toggle);
  video.addEventListener('play',()=>{play.textContent='同步暂停';cancelAnimationFrame(frame);tick();});
  video.addEventListener('pause',()=>{play.textContent='同步播放';cancelAnimationFrame(frame);draw();});
  video.addEventListener('ended',()=>{play.textContent='同步播放';draw();});
  video.addEventListener('loadedmetadata',()=>{seek.max=video.duration;draw();});
  for(const event of ['loadeddata','seeked','timeupdate'])video.addEventListener(event,draw);
  video.addEventListener('error',()=>toast('原片暂时无法播放，请检查硬盘连接',false));
  seek.addEventListener('input',()=>{video.currentTime=Number(seek.value);draw();});
  mute.addEventListener('click',()=>{video.muted=!video.muted;mute.textContent=video.muted?'取消静音':'静音';});
  fullscreen.addEventListener('click',()=>{if(document.fullscreenElement)document.exitFullscreen();else display.requestFullscreen?.();});
  if (video.requestVideoFrameCallback) {
    const decoded = () => { if(disposed)return; draw(); decodedFrame=video.requestVideoFrameCallback(decoded); };
    decodedFrame=video.requestVideoFrameCallback(decoded);
  }
  mark.addEventListener("load",draw);
  draw();
  return {el,video,destroy(){disposed=true;resize.disconnect();cancelAnimationFrame(frame);if(decodedFrame)video.cancelVideoFrameCallback(decodedFrame);video.pause();video.removeAttribute('src');video.load();}};
}

function previewNotes(data) {
  return (data.captions||[]).filter(c=>c.style==='Note').map(c=>({
    start:c.start,end:c.end,style:'Note',lines:[{text:[c.orig,c.zh,c.extra].filter(Boolean).join(' ')}]
  }));
}

// English sits on the picture, with one translated line in the band below it.
function horizontalCaptionBand(video, data) {
  const canvas = h('canvas', {width:480, height:20, 'aria-hidden':'true'});
  const band = h('div', {class:'horizontal-caption-band'}, canvas);
  const picture = h('div', {class:'horizontal-caption-picture'}, video);
  const el = h('div', {class:'stage horizontal-caption-stage'}, picture, band);
  const ctx = canvas.getContext('2d');
  const style = {size:60, color:'#FFFFFF', outline:3, marginL:36, marginR:36, marginV:24, align:2, box:null};
  const english = new SubRenderer(picture, {playResX:1920, playResY:1080, styles:{Default:style}, events:[]});
  const chinese = new SubRenderer(band, {playResX:1920, playResY:56,
    styles:{Default:{...style, align:8, marginV:-22}}, events:[]});
  const notes = previewNotes(data);
  const noteRenderer = new SubRenderer(el, {playResX:1920, playResY:1136, styles:{
    Note:{size:48, color:'#CCFF00', outline:0, marginL:36, marginR:36, marginV:12, align:8, box:null}
  }, events:notes});
  const cues = (data.captions || []).filter(c => c.style !== 'Note' && !c.orig.startsWith('《'));
  let frame = 0, disposed = false;
  function caption(cue, text, renderer, width) {
    text = text.replace(/\s*\n\s*/g, ' ').trim();
    const size = 60 * Math.min(1, (width * 1848 / 1920) / Math.max(1, renderer.width(text, 60)));
    return {start:cue.start, end:cue.end, style:'Default', lines:[{text, size}]};
  }
  function draw() {
    if (disposed) return;
    if (video.readyState >= 2 && video.videoWidth) {
      const strip = Math.max(2, Math.round(video.videoHeight * .035));
      ctx.drawImage(video, 0, video.videoHeight-strip, video.videoWidth, strip, 0, 0, 480, 20);
    }
    if (!chinese.ky || !english.ky) return;
    const time = video.currentTime + (data.start || 0);
    const active = cues.filter(c => c.start <= time && time < c.end);
    english.render(active.map(c => caption(c, c.orig, english, picture.clientWidth)), true);
    chinese.render(active.map(c => caption(c, (c.zh || '').replace(/[♪♫♬🎵🎶]/gu, ''), chinese, band.clientWidth)), true);
    noteRenderer.render(notes.filter(c => c.start <= time && time < c.end));
  }
  function layout() {
    english.layout(picture.clientWidth, picture.clientHeight, video.videoWidth / video.videoHeight || 16/9);
    chinese.layout(band.clientWidth, band.clientHeight, 1920/56);
    noteRenderer.layout(el.clientWidth, el.clientHeight, el.clientWidth/el.clientHeight);
    draw();
  }
  const resize = new ResizeObserver(layout);
  resize.observe(band);
  resize.observe(picture);
  const events = ['loadedmetadata', 'loadeddata', 'seeked', 'timeupdate'];
  events.forEach(event => video.addEventListener(event, layout));
  if (video.requestVideoFrameCallback) {
    const tick = () => { draw(); if (!disposed) frame = video.requestVideoFrameCallback(tick); };
    frame = video.requestVideoFrameCallback(tick);
  }
  return {el, destroy() {
    disposed = true;
    resize.disconnect();
    events.forEach(event => video.removeEventListener(event, layout));
    if (frame) video.cancelVideoFrameCallback(frame);
  }};
}
