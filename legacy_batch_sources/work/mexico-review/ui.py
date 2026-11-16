from playwright.sync_api import sync_playwright
from urllib.request import urlopen
import json
root='http://127.0.0.1:8160'; groups=json.load(urlopen(root+'/api/concerts'))
with sync_playwright() as p:
    b=p.chromium.launch(channel='chrome')
    for key in ('dualipa_mexico2025','super_bowl_halftime','artist_6164656c65'):
        g=next(x for x in groups if x['slug']==key); name=next(x['name'] for x in g['tracks'] if x['portrait_preview_ready'])
        page=b.new_page();page.goto(root+'/#/'+key+'/'+name)
        page.locator('canvas[aria-label="实时竖屏预览"]').wait_for(timeout=45000)
        page.get_by_role('button',name='横竖同步播放',exact=True).first.click()
        page.wait_for_function("Array.from(document.querySelectorAll('video')).some(v=>!v.paused&&v.currentTime>0.5)",timeout=45000)
        print(key,name,'playing',flush=True)
        page.close()
    b.close()
