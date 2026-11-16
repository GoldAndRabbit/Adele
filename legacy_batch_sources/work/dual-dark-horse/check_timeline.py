import asyncio,json
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='chrome',headless=True)
  page=await b.new_page(viewport={'width':1800,'height':1100})
  await page.goto('http://127.0.0.1:8160/#/grammys_2014/04_dark_horse')
  await page.get_by_text('产物',exact=True).click()
  await page.locator('.production-timeline').wait_for()
  ticks=await page.locator('.production-timeline-scale').inner_text()
  assert all(x in ticks for x in ['5min','10min','15min','20min'])
  assert await page.locator('.production-timeline-track').count()==8
  line=await page.locator('.production-timeline-track').first.evaluate("e=>getComputedStyle(e,'::after').backgroundImage")
  assert 'repeating-linear-gradient' in line
  await page.locator('.production-timeline').screenshot(path='work/dual-dark-horse/timeline-grid.png')
  print(json.dumps({'ticks':ticks,'grid':line},ensure_ascii=False))
  await b.close()
asyncio.run(main())
