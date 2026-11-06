const frame=document.getElementById('scene'),stage=document.getElementById('stage'),play=document.getElementById('play'),seek=document.getElementById('seek'),speed=document.getElementById('speed'),loop=document.getElementById('loop'),restart=document.getElementById('restart'),audio=document.getElementById('audio'),offset=document.getElementById('offset');let sceneReady=false;
function fit(){frame.style.transform=`scale(${stage.clientWidth/1080})`}new ResizeObserver(fit).observe(stage);
function length(){return Number.isFinite(audio.duration)?audio.duration:13.4}
function clock(t){return `${String(Math.floor(t/60)).padStart(2,'0')}:${String(Math.floor(t%60)).padStart(2,'0')}`}
function draw(){if(!sceneReady)return;const t=audio.currentTime;frame.contentWindow.drawAt(t-Number(offset.value)/1000);seek.max=length();seek.value=t;document.getElementById('time').textContent=`${clock(t)} / ${clock(length())}`;play.textContent=audio.paused?'播放':'暂停';play.setAttribute('aria-label',audio.paused?'播放音频与动画':'暂停音频与动画')}
function enable(){const ready=sceneReady&&audio.readyState>=1;play.disabled=seek.disabled=restart.disabled=!ready;if(ready)draw()}
async function start(){try{await audio.play();document.getElementById('audio-error').textContent='';draw()}catch(e){document.getElementById('audio-error').textContent='音频未能播放，请点击播放重试。';draw()}}
function toggle(){if(play.disabled)return;if(audio.paused){if(audio.ended)audio.currentTime=0;start()}else audio.pause()}
frame.addEventListener('load',async()=>{await frame.contentDocument.fonts.ready;sceneReady=true;enable()});audio.addEventListener('loadedmetadata',enable);audio.addEventListener('error',()=>{document.getElementById('audio-error').textContent='音频加载失败，请刷新页面。'});
play.onclick=toggle;restart.onclick=()=>{audio.currentTime=0;start()};seek.addEventListener('input',()=>{audio.currentTime=Number(seek.value);draw()});speed.onchange=()=>{audio.playbackRate=Number(speed.value)};offset.oninput=()=>{document.getElementById('offset-value').textContent=`${offset.value} ms`;draw()};loop.onchange=()=>audio.loop=loop.checked;audio.loop=loop.checked;
for(const event of ['pause','play','seeked','ended','timeupdate'])audio.addEventListener(event,draw);
function tick(){draw();requestAnimationFrame(tick)}requestAnimationFrame(tick);
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','BUTTON'].includes(e.target.tagName))return;if(e.code==='Space'){e.preventDefault();toggle()}else if(['ArrowLeft','ArrowRight'].includes(e.code)){e.preventDefault();audio.currentTime=Math.max(0,Math.min(length(),audio.currentTime+(e.code==='ArrowRight'?1:-1)));draw()}});

// Buffer the short preview locally so seeking works even on a basic HTTP server without Range support.
(async()=>{try{const r=await fetch(audio.dataset.src);if(!r.ok)throw new Error('HTTP '+r.status);audio.src=URL.createObjectURL(await r.blob());audio.load()}catch(e){document.getElementById('audio-error').textContent='音频加载失败，请刷新页面。'}})();
