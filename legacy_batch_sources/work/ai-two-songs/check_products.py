import asyncio,json,sys
from pathlib import Path
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='chrome',headless=True);page=await b.new_page(viewport={'width':1800,'height':1100});results=[]
  for name in sys.argv[1:]:
   await page.goto('http://127.0.0.1:8160/#/grammys_2014/'+name);await page.get_by_text('产物',exact=True).click()
   rows=[]
   for sel,size in [('.product-horizontal video',(3840,2160)),('.product-portrait video',(1080,1920))]:
    v=page.locator(sel);await v.wait_for();await v.evaluate('(v)=>{v.muted=true;v.currentTime=17;}');await v.evaluate('(v)=>v.play()');await page.wait_for_timeout(1200)
    r=await v.evaluate('(v)=>({time:v.currentTime,width:v.videoWidth,height:v.videoHeight,error:v.error?.message})');assert (r['width'],r['height'])==size and r['time']>17.5 and not r.get('error'),r
    await v.evaluate('(v)=>v.pause()');rows.append(r)
   await page.locator('.production-timeline').screenshot(path=f'work/ai-two-songs/{name}/timing.png')
   results.append({'song':name,'players':rows,'timing':await page.locator('.production-timeline').inner_text()})
  Path('work/ai-two-songs/ui-products-'+sys.argv[1]+'.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False));await b.close()
asyncio.run(main())
