import asyncio
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='chrome',headless=True);page=await b.new_page(viewport={'width':1800,'height':1100})
  await page.goto('http://127.0.0.1:8160/#/an_audience_with_adele_2021/01_hometown_glory')
  await page.wait_for_selector('.pool-selector-hint')
  assert await page.locator('[aria-label="封面比例"]').count()==0
  await page.goto('http://127.0.0.1:8160/#/an_audience_with_adele_2021/~covers')
  await page.wait_for_selector('.raw-pool-grid .pool-frame-card')
  columns=await page.locator('.raw-pool-grid').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length');assert columns==10
  done=page.get_by_role('button',name='标记完成',exact=True);grid=page.locator('.raw-pool-grid');assert (await done.bounding_box())['y']<(await grid.bounding_box())['y']
  await page.locator('.pool-frame-image').first.click();await page.wait_for_selector('.pool-frame-dialog[open]')
  assert await page.locator('.pool-frame-dialog .pool-frame-pick').count()==1
  await page.screenshot(path='work/cover-pool-upgrade/dialog.png')
  await page.get_by_role('button',name='关闭放大').click();await page.screenshot(path='work/cover-pool-upgrade/grid.png')
  print('UI_OK hidden unselected,10 columns,button above,click modal,pick top right')
  await b.close()
asyncio.run(main())
