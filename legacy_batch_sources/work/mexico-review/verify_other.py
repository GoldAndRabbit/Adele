from urllib.request import urlopen, Request
from pathlib import Path
import json
from playwright.sync_api import sync_playwright
root='http://127.0.0.1:8160'
groups=json.load(urlopen(root+'/api/concerts'))
result=[]
with sync_playwright() as pw:
    b=pw.chromium.launch(channel='chrome',headless=True)
    page=b.new_page()
    page.goto(root+'/docs')
    for group in groups:
        if group.get('kind') or group['slug']=='dualipa_mexico2025':continue
        for track in group['tracks']:
            name=track['name'];slug=group['slug']
            row=dict(group=group['title'],slug=slug,name=name,title=track['title'],review=root+'/#/'+slug+'/'+name);result.append(row)
            try:
                song=json.load(urlopen(root+'/api/concerts/'+slug+'/songs/'+name))
                p=song.get('browser_portrait')
                if not p:raise ValueError('尚无竖屏实时预览')
                if not (p['header_text']['song'] and p['header_text']['en'] and p['header_text']['event']):raise ValueError('缺少片头')
                row['bilingual_lines']=sum(bool(c['orig'] and c['zh']) for c in p['captions'])
                if not row['bilingual_lines']:raise ValueError('缺少双语字幕')
                for link in {song['preview'],p['url']}:
                    with urlopen(Request(root+link, headers={'Range':'bytes=0-63'}),timeout=15) as r:
                        if r.status!=206 or b'ftyp' not in r.read(64):raise ValueError('视频读取失败')
                frame=page.evaluate("""async url=>{const v=document.createElement('video');v.src=url;v.muted=true;document.body.append(v);try{return await Promise.race([new Promise((resolve,reject)=>{v.onerror=()=>reject(Error('视频解码失败'));v.onloadedmetadata=()=>{v.currentTime=Math.min(5,v.duration/2);v.requestVideoFrameCallback(()=>resolve([v.videoWidth,v.videoHeight,v.duration]));v.play().catch(reject)}}),new Promise((_,r)=>setTimeout(()=>r(Error('视频首帧超时')),15000))])}finally{v.pause();v.removeAttribute('src');v.load();v.remove()}}""",p['url'])
                row['media']=frame
                if not frame[0] or frame[2]<=0:raise ValueError('视频范围不符')
                row['douyin']=bool(song.get('douyin_submission',{}).get('title'))
                row['bilibili']=bool(song.get('bili_upload') or song.get('draft'))
                row['status']='ready'
            except Exception as exc:row.update(status='pending',reason=str(exc))
    b.close()
out=Path('work/mexico-review/other-groups.json');out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
from collections import Counter
print(Counter(r['status'] for r in result),Counter(r.get('reason') for r in result if r['status']!='ready'))
