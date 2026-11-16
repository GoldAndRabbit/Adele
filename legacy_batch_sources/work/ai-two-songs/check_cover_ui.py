import asyncio,json
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='chrome',headless=True);page=await b.new_page(viewport={'width':1800,'height':1100});results=[]
  for name in ['01_drunk_in_love','02_royals']:
   url='http://127.0.0.1:8160/#/grammys_2014/'+name;await page.goto(url)
   await page.get_by_text('封面设计',exact=True).click();await page.get_by_text('AI 生成',exact=True).click()
   response=await page.request.get('http://127.0.0.1:8160/api/concerts/grammys_2014/songs/'+name+'/cover_design');data=await response.json()
   for row in data['generated']+data['variants']:
    res=await page.request.get('http://127.0.0.1:8160'+row['url']);assert res.ok,row['url']
   results.append({'song':name,'masters':len(data['generated']),'variants':len(data['variants']),'failures':len(data['failed_candidates'])})
   await page.screenshot(path=f'work/ai-two-songs/{name}/ui-ai.png',full_page=True)
  print(json.dumps(results));await b.close()
asyncio.run(main())
