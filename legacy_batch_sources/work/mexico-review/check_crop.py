from playwright.sync_api import sync_playwright
from PIL import Image
from io import BytesIO
import numpy as np
from urllib.request import urlopen
import json
root='http://127.0.0.1:8160'; slug='dualipa_mexico2025'; route=root+'/api/concerts/'+slug
rows=json.load(urlopen(route))['songs']
for it in rows:
 data=json.load(urlopen(route+'/songs/'+it['name']))['browser_portrait']; box=data['preview_crop'];assert box and box==data['box'] and data['captions']
 print(it['name'],[round(box[k]*size) for k,size in zip(('x','y','w','h'),(1920,1080,1920,1080))])
with sync_playwright() as pw:
 b=pw.chromium.launch(channel='chrome');p=b.new_page(viewport={'width':1720,'height':980})
 p.goto(root+'/#/'+slug+'/01_training_season')
 v=p.locator('video.shared-review-source');v.wait_for();v.evaluate("async v=>{await new Promise(r=>{v.addEventListener('seeked',r,{once:true});v.currentTime=243});v.controls=false;v.closest('.stage').querySelectorAll('.subs').forEach(e=>e.style.visibility='hidden')}")
 img=np.asarray(Image.open(BytesIO(v.screenshot())).convert('RGB'));h,w=img.shape[:2];print('viewport',w,h,'edge brightness',img[5:h//10].max(axis=2).mean(),img[-h//10:-5].max(axis=2).mean(),v.evaluate("v=>[CSS.supports('object-view-box','inset(10%)'),getComputedStyle(v).objectViewBox]"));assert abs(w/h-2.4)<.03 and img[5:h//10].max(axis=2).mean()>10 and img[-h//10:-5].max(axis=2).mean()>10
 b.close()
