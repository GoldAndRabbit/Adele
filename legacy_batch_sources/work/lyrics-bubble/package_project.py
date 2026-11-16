from pathlib import Path
import re,json,shutil
src=Path('work/lyrics-bubble');p=Path('lyrics_rolling_video');(p/'templates').mkdir(parents=True,exist_ok=True);(p/'preview').mkdir(exist_ok=True);(p/'data').mkdir(exist_ok=True)
for name in ['aligned-audio.m4a','aligned-player.js']:
 shutil.copy(src/'local-preview'/name,p/'preview'/name)
shutil.copy(src/'alignment.json',p/'alignment.json')
shutil.copy(src/'source.webm',p/'data/source.webm')
old=(src/'local-preview/scene.html').read_text();svg=re.search(r'<svg.*?</svg>',old,re.S).group()
(p/'templates/defs.svg').write_text(re.search(r'<defs>.*?</defs>',svg).group())
shell=re.sub(r'<script>.*?</script>','',old,flags=re.S).replace(svg,'{{SCENE}}');(p/'templates/scene.html').write_text(shell)
index=(src/'local-preview/index.html').read_text().replace('Ramenez la coupe à la maison · Vegedream','{{SONG}}').replace('原曲 01:10.5–01:23.9','{{EXCERPT}}')
(p/'templates/index.html').write_text(index)
a=json.loads((src/'alignment.json').read_text())
config={'source_url':'https://www.youtube.com/watch?v=u7j--YMXZtA','source_start':70.5,'duration':13.4,'title':['Ramenez la coupe','à la maison'],'title_zh':'把奖杯带回家','artist':'Vegedream','language':'fr','language_label':'法语','lines':a['lines'],'phrase_groups':[[[0,1],[1,3]],[[0,3],[3,5]],[[0,1],[1,2]],[[0,1],[1,2]],[[0,2],[2,3]],[[0,1],[1,2]],[[0,2],[2,5]],[[0,2]],[[0,2],[2,5]],[[0,2]]]}
(p/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
b=(src/'build_aligned.py').read_text();start=b.index("s=['<svg");end=b.index("index=(root/'index.html')")
b=b[start:end]
b=b.replace("re.search(r'<defs>.*?</defs>',svg).group()","(p/'templates/defs.svg').read_text()").replace("re.search(r'<image .*?/>',svg).group()",'logo')
b=b.replace("'Ramenez la coupe'","config['title'][0]").replace("'à la maison'","config['title'][1]").replace("'把奖杯带回家'","config['title_zh']").replace("'Vegedream  ·  法语歌词'","config['artist']+'  ·  '+config['language_label']+'歌词'")
b=b.replace("'原曲片段 01:10.5—01:23.9 · 自动对齐试听版'","excerpt+' · 自动对齐试听版'")
b=re.sub(r'splits=\{.*?\}\n','splits=dict(enumerate(config["phrase_groups"]))\n',b)
b=b.replace("chunk=words[a:b];assert chunk","assert 0 <= a < b <= len(words), f'第 {li+1} 行词组范围不合法'\n  chunk=words[a:b]")
b=b.replace("new=re.sub(r'<script>.*?</script>','',old,flags=re.S).replace(svg,''.join(s))+js","new=(p/'templates/scene.html').read_text().replace('{{SCENE}}',''.join(s))+js")
header='''"""Rebuild the preview from checked lyrics and saved word alignment; no network calls."""
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
'''
footer='''
index=(p/'templates/index.html').read_text().replace('{{SONG}}',html.escape(' '.join(config['title'])+' · '+config['artist'])).replace('{{EXCERPT}}',html.escape(excerpt))
(root/'index.html').write_text(index)
print(f"Built {len(cues)} phrase cues in {root}")
'''
(p/'build.py').write_text(header+b+footer)
f=(src/'force_align.py').read_text();f=f.replace("sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'workflow')]","BASE=Path(__file__).resolve().parent\nsys.path[:0]=[str(BASE.parent),str(BASE.parent/'workflow')]")
f=re.sub(r"p=Path\('work/lyrics-bubble'\)\nlines=.*?\ntorch", "p=BASE\nconfig=json.loads((p/'config.json').read_text())\nlines=[(x['fr'],x['zh']) for x in config['lines']]\ntorch",f,flags=re.S)
f=f.replace("p/'align.wav'","p/'data/align.wav'").replace("romanize(m.group(),'fr')","romanize(m.group(),config['language'])").replace("'source_start':70.5,'duration':13.4","'source_start':config['source_start'],'duration':config['duration']")
(p/'align.py').write_text(f)
