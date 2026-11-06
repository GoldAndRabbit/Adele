"""Rebuild the preview from checked lyrics and saved word alignment; no network calls."""
from pathlib import Path
import json,html,base64
p=Path(__file__).resolve().parent
root=p/'preview';root.mkdir(exist_ok=True)
config=json.loads((p/'config.json').read_text())
data=json.loads((p/'alignment.json').read_text())
assert data['lines']==config['lines'], '歌词修改后须重新运行 prepare.py，不能沿用旧字符位置'
assert data['source_start']==config['source_start'] and data['duration']==config['duration'], '音频范围变化后须重新对齐'
assert len(config['lines'])==len(config['phrase_groups']) and 0<len(config['lines'])<=10
assert len(config['title'])==2, '标题目前使用两行'
def stamp(t): return f"{int(t//60):02d}:{t%60:04.1f}"
excerpt=f"原曲片段 {stamp(config['source_start'])}—{stamp(config['source_start']+config['duration'])}"
encoded=base64.b64encode((p.parent/'assets/adele-logo.png').read_bytes()).decode()
logo=f'<image x="72" y="138" width="215" height="68.6" opacity=".85" xlink:href="data:image/png;base64,{encoded}"/>'
s=['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1080" height="1920">',(p/'templates/defs.svg').read_text(),'<rect width="1080" height="1920" fill="url(#bg)"/>',logo]
def txt(x,y,t,size=30,fill='#c2b8d1',extra=''):
 s.append(f'<text x="{x}" y="{y}" font-family="Arial, PingFang SC, sans-serif" font-size="{size}" fill="{fill}" {extra}>{html.escape(t)}</text>')
txt(72,285,config['title'][0],53,'#f5f1fa','font-weight="700"');txt(72,350,config['title'][1],53,'#f5f1fa','font-weight="700"');txt(72,404,config['title_zh'],29);txt(72,466,config['artist']+'  ·  '+config['language_label']+'歌词',28)
s.append('<path d="M72 510 H910" stroke="#c9bddc" stroke-opacity=".15"/>');txt(72,551,'原曲音频 / 词组跟唱',22)
s.append('<rect id="bubble" rx="15" fill="#d6c7f3" fill-opacity=".23" stroke="#e4daf8" stroke-opacity=".28"/>')
for i,line in enumerate(data['lines']):
 txt(78,623+i*98,line['fr'],48,'#b6a9c7',f'id="l{i}"');txt(80,663+i*98,line['zh'],25,'#8f819f',f'id="z{i}"')
s.append('<path d="M72 1660 H910" stroke="#857994" stroke-opacity=".3"/><path id="progress" d="M72 1660 H72" stroke="#e5c5a5" stroke-width="3"/>');txt(72,1720,excerpt+' · 自动对齐试听版',22,'#9c90ac');txt(72,1765,'歌词来自提供的截图 · 中文为参考译文',20,'#756982');s.append('</svg>')
# Groups are slices of aligned words, never evenly divided line durations.
splits=dict(enumerate(config["phrase_groups"]))
cues=[]
for li,groups in splits.items():
 words=[w for w in data['words'] if w['line']==li]
 assert [i for a,b in groups for i in range(a,b)]==list(range(len(words))), f'第 {li+1} 行词组须按顺序完整覆盖所有词'
 for a,b in groups:
  assert 0 <= a < b <= len(words), f'第 {li+1} 行词组范围不合法'
  chunk=words[a:b]
  cues.append({'start':chunk[0]['start'],'end':chunk[-1]['end'],'line':li,'char_start':chunk[0]['char_start'],'char_end':chunk[-1]['char_end']})
data['cues']=cues;(root/'alignment.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
js='''<script>window.alignment=DATA;const cues=alignment.cues;const bubble=document.getElementById('bubble');
function rect(c){const e=document.getElementById('l'+c.line),p=e.getStartPositionOfChar(c.char_start);return [p.x-12,Number(e.getAttribute('y'))-49,e.getSubStringLength(c.char_start,c.char_end-c.char_start)+24,65]}
window.drawAt=function(t){let n=-1;for(let i=0;i<cues.length;i++)if(cues[i].start<=t)n=i;const c=n<0?cues[0]:cues[n];const on=n>=0&&t<=c.end+.1;const prev=cues[Math.max(0,n-1)];let f=Math.max(0,Math.min(1,(t-c.start)/.11));f=f*f*(3-2*f);const a=rect(prev),b=rect(c),r=a.map((v,i)=>v+(b[i]-v)*f);['x','y','width','height'].forEach((k,i)=>bubble.setAttribute(k,r[i]));bubble.style.opacity=on?'1':'0';bubble.dataset.cue=n;for(let i=0;i<alignment.lines.length;i++){document.getElementById('l'+i).setAttribute('fill',on&&i===c.line?'#fff4e4':'#b6a9c7');document.getElementById('z'+i).setAttribute('fill',on&&i===c.line?'#dec7ad':'#8f819f')}document.getElementById('progress').setAttribute('d','M72 1660 H'+(72+838*Math.max(0,Math.min(1,t/alignment.duration))));window.lastDrawTime=t;};document.fonts.ready.then(()=>drawAt(0));</script>'''.replace('DATA',json.dumps(data,ensure_ascii=False).replace('<', r'\u003c'))
new=(p/'templates/scene.html').read_text().replace('{{SCENE}}',''.join(s))+js
(root/'scene-aligned.html').write_text(new)

index=(p/'templates/index.html').read_text().replace('{{SONG}}',html.escape(' '.join(config['title'])+' · '+config['artist'])).replace('{{EXCERPT}}',html.escape(excerpt))
(root/'index.html').write_text(index)
print(f"Built {len(cues)} phrase cues in {root}")
(root/'aligned-player.js').write_text((p/'templates/aligned-player.js').read_text())
