from playwright.sync_api import sync_playwright
from pathlib import Path
import json, argparse
parser=argparse.ArgumentParser()
parser.add_argument("--url",default="http://127.0.0.1:8765/")
parser.add_argument("--browser",default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
args=parser.parse_args()
base=Path(__file__).resolve().parent/'exports';base.mkdir(exist_ok=True)
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=args.browser,headless=True)
 page=b.new_page(viewport={'width':1400,'height':1050});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 response=page.goto(args.url);page.wait_for_function("!document.getElementById('play').disabled")
 assert page.locator('#play').inner_text()=='播放'
 page.click('#play');page.wait_for_timeout(900)
 assert page.evaluate("document.getElementById('audio').currentTime")>.4
 page.click('#play');t=page.evaluate("document.getElementById('audio').currentTime");page.wait_for_timeout(150)
 assert abs(page.evaluate("document.getElementById('audio').currentTime")-t)<.03
 page.locator('#seek').fill('6.2');page.locator('#seek').dispatch_event('input');page.wait_for_timeout(150)
 result=page.evaluate("({audio:document.getElementById('audio').currentTime,draw:document.getElementById('scene').contentWindow.lastDrawTime,cue:document.getElementById('scene').contentDocument.getElementById('bubble').dataset.cue})")
 assert abs(result['audio']-6.2)<.03,result;assert abs(result['audio']-result['draw'])<.02,result
 page.select_option('#speed','0.5');assert page.evaluate("document.getElementById('audio').playbackRate")==.5
 page.locator('#offset').fill('200');page.locator('#offset').dispatch_event('input');page.wait_for_timeout(50)
 print('offset state',page.evaluate("({t:document.getElementById('audio').currentTime,draw:document.getElementById('scene').contentWindow.lastDrawTime,offset:document.getElementById('offset').value,paused:document.getElementById('audio').paused})")); assert abs(page.evaluate("document.getElementById('scene').contentWindow.lastDrawTime-(document.getElementById('audio').currentTime-.2)"))<.03
 assert abs(page.evaluate("document.getElementById('audio').currentTime")-6.2)<.03
 page.locator('#offset').fill('0');page.locator('#offset').dispatch_event('input');page.select_option('#speed','1')
 frame=page.frames[1]
 boxes=frame.evaluate("alignment.cues.map(c=>{let e=document.getElementById('l'+c.line),p=e.getStartPositionOfChar(c.char_start);return {x:p.x,w:e.getSubStringLength(c.char_start,c.char_end-c.char_start)}})")
 assert all(x['x']+x['w']<960 for x in boxes),boxes
 page.screenshot(path=str(base/'verification.png'))
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(100);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 assert not errors,errors
 print('PASS: audio play/pause, seek and frame clock, playback speed, offset, phrase bounds, mobile layout. HTTP',response.status)
 b.close()
