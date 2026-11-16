import asyncio,json
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='chrome',headless=True)
  page=await b.new_page(viewport={'width':1800,'height':1100})
  for slug,name in [('an_evening_with_dua_lipa_cbs_2024','01_houdini')]:
   page=await b.new_page(viewport={'width':1800,'height':1100})
   response=await page.request.get(f'http://127.0.0.1:8160/api/concerts/{slug}/songs/{name}');data=await response.json()
   assert data['browser_portrait'] and data['douyin_submission']['title_chars']<=30
   await page.goto(f'http://127.0.0.1:8160/#/{slug}/{name}')
   await page.wait_for_selector('.browser-portrait-stage canvas')
   v=page.locator('video.shared-review-source');await v.evaluate('(v)=>{v.muted=true;v.currentTime=40;}')
   await v.evaluate('(v)=>v.play()');await page.wait_for_timeout(2200)
   result=await v.evaluate('(v)=>({time:v.currentTime,error:v.error?.message,ready:v.readyState,paused:v.paused})')
   assert result['time']>40.5 and not result['error'],result
   await v.evaluate('(v)=>v.pause()')
   await page.screenshot(path=f'work/cover-berry/{slug}-ui.png',full_page=False)
   print(slug,result)
  await b.close()
asyncio.run(main())
