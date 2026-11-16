from pathlib import Path
import re,json,html
out=Path('/Users/gold/Documents/Codex/2026-11-04/referenced-chatgpt-conversation-this-is-an/outputs')
old=(out/'portrait-perspective-v2.html').read_text()
svg=re.search(r'<svg.*?</svg>',old,re.S).group()
logo=re.search(r'<image .*?/>',svg).group()
lines=[('Passement de jambe','跨步假动作'),('Crochet à gauche, à droite','向左变向，再向右'),('Kylian Mbappé','基利安·姆巴佩'),('Accélération, virgule,','加速、甩牛尾巴'),('petit-pont, frappe','穿裆，射门'),('Kylian Mbappé','基利安·姆巴佩'),("Je tire des deux pieds,",'我双脚都能射门'),('Ousmane Dembélé','奥斯曼·登贝莱')]
s=['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1080" height="1920">',re.search(r'<defs>.*?</defs>',svg).group(),'<rect width="1080" height="1920" fill="url(#bg)"/>',logo]
def txt(x,y,t,size=30,fill='#c2b8d1',extra=''):
 s.append(f'<text x="{x}" y="{y}" font-family="Arial, PingFang SC, sans-serif" font-size="{size}" fill="{fill}" {extra}>{html.escape(t)}</text>')
txt(72,285,'Ramenez la coupe',53,'#f5f1fa','font-weight="700"');txt(72,350,'à la maison',53,'#f5f1fa','font-weight="700"')
txt(72,404,'把奖杯带回家',29);txt(72,466,'Vegedream  ·  法语歌词',28)
s.append('<path d="M72 510 H910" stroke="#c9bddc" stroke-opacity=".15"/>')
txt(72,551,'词组跟唱 / 动效预览',22)
s.append('<rect id="bubble" rx="17" fill="#d6c7f3" fill-opacity=".23" stroke="#e4daf8" stroke-opacity=".28"/>')
for i,(fr,zh) in enumerate(lines):
 txt(78,635+i*122,fr,51,'#e6dfee',f'id="l{i}"');txt(80,681+i*122,zh,28,'#9a8eae',f'id="z{i}"')
s.append('<path d="M72 1660 H910" stroke="#857994" stroke-opacity=".3"/><path id="progress" d="M72 1660 H72" stroke="#e5c5a5" stroke-width="3"/>')
txt(72,1720,'无声样片 · 模拟节奏，尚未对齐歌曲音频',22,'#9c90ac')
txt(72,1765,'歌词取自你提供的截图 · 中文为参考译文',20,'#756982')
s.append('</svg>')
new=old.replace(svg,''.join(s)).replace('width:1080px;height:1920px;overflow:hidden','width:1080px;height:1920px;overflow:hidden')
# Two phrase targets in a line demonstrate rightward motion; subsequent rows return left.
cues=[(0,0,0,9),(1.1,0,10,8),(2.1,1,0,16),(3.3,1,18,8),(4.4,2,0,13),(5.6,3,0,13),(6.7,3,14,8),(7.8,4,0,10),(8.8,4,12,6),(9.8,5,0,13),(10.9,6,0,7),(11.9,6,8,14),(13.2,7,0,15)]
# Clamp ranges to exact source string lengths.
cues=[(t,i,start,min(n,len(lines[i][0])-start)) for t,i,start,n in cues]
js='''<script>const cues=CUES;const duration=15;let running=!new URLSearchParams(location.search).has('render'),offset=0,epoch=performance.now();
function rect(c){let e=document.getElementById('l'+c[1]);let p=e.getStartPositionOfChar(c[2]);return [p.x-13,Number(e.getAttribute('y'))-53,e.getSubStringLength(c[2],c[3])+26,72]}
window.drawAt=function(t){t=Math.max(0,Math.min(t,14.999));let n=0;for(let i=0;i<cues.length;i++)if(cues[i][0]<=t)n=i;let a=rect(cues[Math.max(0,n-1)]),b=rect(cues[n]);let f=Math.min(1,(t-cues[n][0])/.28);f=f*f*(3-2*f);let r=a.map((v,i)=>v+(b[i]-v)*f);['x','y','width','height'].forEach((k,i)=>document.getElementById('bubble').setAttribute(k,r[i]));for(let i=0;i<8;i++){document.getElementById('l'+i).setAttribute('fill',i===cues[n][1]?'#fff4e4':'#b6a9c7');document.getElementById('z'+i).setAttribute('fill',i===cues[n][1]?'#dec7ad':'#8f819f')}document.getElementById('progress').setAttribute('d','M72 1660 H'+(72+838*t/duration));};
function tick(now){if(running)drawAt(((now-epoch)/1000+offset)%duration);requestAnimationFrame(tick)}document.fonts.ready.then(()=>{drawAt(0);requestAnimationFrame(tick)});document.addEventListener('click',()=>{if(running){offset=((performance.now()-epoch)/1000+offset)%duration;running=false}else{epoch=performance.now();running=true}});</script>'''.replace('CUES',json.dumps(cues))
new+=js
(out/'vegedream-bubble-demo.html').write_text(new)
