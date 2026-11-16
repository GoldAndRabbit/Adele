from pathlib import Path
from playwright.sync_api import sync_playwright
from workflow.live.paths import Concert,read_json
from workflow.vertical_cover import original_source
from workflow.browser_library import prepare_browser,probe,BASE
from urllib.request import urlopen
import json
c=Concert('singles')
names={t['name'] for g in json.load(urlopen('http://127.0.0.1:8160/api/concerts')) if g.get('kind') for t in g['tracks']}
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page()
    for it in reversed(c.song_items()):
        if it['name'] not in names:continue
        d=c.song_dir(it);p=original_source(c,it).resolve();folder=BASE/c.slug/'browser-sources'/it['name']
        if folder.exists():continue
        m=probe(p);v=next(z for z in m['streams'] if z['codec_type']=='video')
        a,b=read_json(d/'song.json')['slice']
        if a or abs(b-float(m['format']['duration']))>.25 or v.get('field_order') in ('tt','bb','tb','bt') or v.get('color_transfer') in ('arib-std-b67','smpte2084'):continue
        page.goto('file://'+str(p))
        ok=page.evaluate("""async()=>{const v=document.querySelector('video');if(!v)return false;v.muted=true;try {await Promise.race([v.play(),new Promise((_,r)=>setTimeout(()=>r('timeout'),8000))]);await new Promise(r=>setTimeout(r,2500));const q=v.getVideoPlaybackQuality();return v.videoWidth>0 && v.currentTime>1.8 && q.totalVideoFrames>=32 && q.droppedVideoFrames/q.totalVideoFrames<0.05}catch{return false}}""")
        if ok:
            prepare_browser(c,it,native_playback_verified=True)
            print('native',it['name'],flush=True)
    browser.close()
