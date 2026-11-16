from playwright.sync_api import sync_playwright
from pathlib import Path
import subprocess
out=Path('/Users/gold/Documents/Codex/2026-11-04/referenced-chatgpt-conversation-this-is-an/outputs')
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
 page=browser.new_page(viewport={'width':720,'height':1280},device_scale_factor=1)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto((out/'vegedream-bubble-demo.html').as_uri()+'?render=1')
 page.add_style_tag(content='html {zoom: 0.6666666667;}')
 page.evaluate('document.fonts.ready')
 enc=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','image2pipe','-vcodec','mjpeg','-framerate','30','-i','-','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(out/'vegedream-bubble-demo.mp4')],stdin=subprocess.PIPE)
 for i in range(450):
  page.evaluate('(t)=>drawAt(t)',i/30)
  if i==210:page.screenshot(path=str(out/'vegedream-bubble-poster.png'))
  enc.stdin.write(page.screenshot(type='jpeg',quality=90))
  if i%90==0:print('frames',i,flush=True)
 enc.stdin.close();assert enc.wait()==0
 print('page errors',errors);assert not errors
 browser.close()
