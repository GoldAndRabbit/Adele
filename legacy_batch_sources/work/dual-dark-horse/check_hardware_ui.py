import asyncio,json
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='chrome',headless=True)
  page=await b.new_page(viewport={'width':1800,'height':1100})
  await page.goto('http://127.0.0.1:8160/#/grammys_2014/04_dark_horse')
  await page.get_by_text('产物',exact=True).click();results=[]
  for selector in ['.product-horizontal video','.product-portrait video']:
   v=page.locator(selector);await v.wait_for()
   await v.evaluate('(v)=>{v.muted=true;v.currentTime=17;}')
   await v.evaluate('(v)=>v.play()');await page.wait_for_timeout(1500)
   r=await v.evaluate('(v)=>({time:v.currentTime,width:v.videoWidth,height:v.videoHeight,error:v.error?.message})')
   assert r['time']>17.5 and not r.get('error'),r
   results.append(r);await v.evaluate('(v)=>v.pause()')
  chart=page.locator('.production-timeline');text=await chart.inner_text()
  assert '4分45秒' in text and '2分22秒' in text,text
  await chart.screenshot(path='work/dual-dark-horse/hardware-timeline.png')
  print(json.dumps({'playback':results,'timeline':text},ensure_ascii=False))
  await b.close()
asyncio.run(main())
