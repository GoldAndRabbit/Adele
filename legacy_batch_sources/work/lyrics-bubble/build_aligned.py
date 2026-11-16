from pathlib import Path
import re,json,html,shutil
p=Path('work/lyrics-bubble');root=p/'local-preview';data=json.loads((p/'alignment.json').read_text());old=(root/'scene.html').read_text();svg=re.search(r'<svg.*?</svg>',old,re.S).group()
s=['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1080" height="1920">',re.search(r'<defs>.*?</defs>',svg).group(),'<rect width="1080" height="1920" fill="url(#bg)"/>',re.search(r'<image .*?/>',svg).group()]
def txt(x,y,t,size=30,fill='#c2b8d1',extra=''):
 s.append(f'<text x="{x}" y="{y}" font-family="Arial, PingFang SC, sans-serif" font-size="{size}" fill="{fill}" {extra}>{html.escape(t)}</text>')
txt(72,285,'Ramenez la coupe',53,'#f5f1fa','font-weight="700"');txt(72,350,'à la maison',53,'#f5f1fa','font-weight="700"');txt(72,404,'把奖杯带回家',29);txt(72,466,'Vegedream  ·  法语歌词',28)
s.append('<path d="M72 510 H910" stroke="#c9bddc" stroke-opacity=".15"/>');txt(72,551,'原曲音频 / 词组跟唱',22)
s.append('<rect id="bubble" rx="15" fill="#d6c7f3" fill-opacity=".23" stroke="#e4daf8" stroke-opacity=".28"/>')
for i,line in enumerate(data['lines']):
 txt(78,623+i*98,line['fr'],48,'#b6a9c7',f'id="l{i}"');txt(80,663+i*98,line['zh'],25,'#8f819f',f'id="z{i}"')
s.append('<path d="M72 1660 H910" stroke="#857994" stroke-opacity=".3"/><path id="progress" d="M72 1660 H72" stroke="#e5c5a5" stroke-width="3"/>');txt(72,1720,'原曲片段 01:10.5—01:23.9 · 自动对齐试听版',22,'#9c90ac');txt(72,1765,'歌词来自提供的截图 · 中文为参考译文',20,'#756982');s.append('</svg>')
# Groups are slices of aligned words, never evenly divided line durations.
splits={0:[(0,1),(1,3)],1:[(0,3),(3,5)],2:[(0,1),(1,2)],3:[(0,1),(1,2)],4:[(0,2),(2,3)],5:[(0,1),(1,2)],6:[(0,2),(2,5)],7:[(0,2)],8:[(0,2),(2,5)],9:[(0,2)]}
cues=[]
for li,groups in splits.items():
 words=[w for w in data['words'] if w['line']==li]
 for a,b in groups:
  chunk=words[a:b];assert chunk
  cues.append({'start':chunk[0]['start'],'end':chunk[-1]['end'],'line':li,'char_start':chunk[0]['char_start'],'char_end':chunk[-1]['char_end']})
data['cues']=cues;(root/'alignment.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
js='''<script>window.alignment=DATA;const cues=alignment.cues;const bubble=document.getElementById('bubble');
function rect(c){const e=document.getElementById('l'+c.line),p=e.getStartPositionOfChar(c.char_start);return [p.x-12,Number(e.getAttribute('y'))-49,e.getSubStringLength(c.char_start,c.char_end-c.char_start)+24,65]}
window.drawAt=function(t){let n=-1;for(let i=0;i<cues.length;i++)if(cues[i].start<=t)n=i;const c=n<0?cues[0]:cues[n];const on=n>=0&&t<=c.end+.1;const prev=cues[Math.max(0,n-1)];let f=Math.max(0,Math.min(1,(t-c.start)/.11));f=f*f*(3-2*f);const a=rect(prev),b=rect(c),r=a.map((v,i)=>v+(b[i]-v)*f);['x','y','width','height'].forEach((k,i)=>bubble.setAttribute(k,r[i]));bubble.style.opacity=on?'1':'0';bubble.dataset.cue=n;for(let i=0;i<alignment.lines.length;i++){document.getElementById('l'+i).setAttribute('fill',on&&i===c.line?'#fff4e4':'#b6a9c7');document.getElementById('z'+i).setAttribute('fill',on&&i===c.line?'#dec7ad':'#8f819f')}document.getElementById('progress').setAttribute('d','M72 1660 H'+(72+838*Math.max(0,Math.min(1,t/alignment.duration))));window.lastDrawTime=t;};document.fonts.ready.then(()=>drawAt(0));</script>'''.replace('DATA',json.dumps(data,ensure_ascii=False))
new=re.sub(r'<script>.*?</script>','',old,flags=re.S).replace(svg,''.join(s))+js
(root/'scene-aligned.html').write_text(new)
index=(root/'index.html').read_text();
if not (root/'demo.html').exists():shutil.copy(root/'index.html',root/'demo.html')
index=index.replace('scene.html?render=1','scene-aligned.html?v=1').replace('无声动效样片 · 模拟节奏','原曲音频 · 自动对齐试听版').replace('00:00 / 00:15','00:00 / 00:13').replace('max="15"','max="13.4"').replace('歌词来自提供的截图；尚未对齐原曲音频。','歌词来自提供的截图，气泡时间来自实际音频的词级对齐。若感觉有轻微早晚，可调整下方偏移试听。').replace('小角度透视、大字歌词，词组间平滑移动。','原曲 01:10.5–01:23.9，试听词组与气泡是否合拍。')
index=index.replace('<small>气泡', '<div class="row"><label for="offset">气泡时间微调</label><span id="offset-value">0 ms</span></div><input id="offset" type="range" min="-500" max="500" step="10" value="0" aria-label="气泡时间微调"><small>负值提前，正值延后。默认使用模型对齐结果。</small><p id="audio-error" role="status"></p><small>气泡')
index=index.replace('<main>','<audio id="audio" src="aligned-audio.m4a?v=1" preload="auto"></audio><main>')
index=re.sub(r'<script>.*?</script>','<script src="aligned-player.js?v=1"></script>',index,flags=re.S)
(root/'index.html').write_text(index)
print('built',len(cues),'phrases; audio duration',data['duration'])
