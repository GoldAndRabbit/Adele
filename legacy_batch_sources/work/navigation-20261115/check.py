import json,time,urllib.parse,requests,concurrent.futures
from pathlib import Path
from playwright.sync_api import sync_playwright
groups=json.load(open('/tmp/adele-all-groups.json'))
base='http://127.0.0.1:8160'
def nav(group):
 t=time.monotonic();r=requests.get(base+'/api/concerts/'+group['slug']+'?navigation=true',timeout=30);r.raise_for_status();data=r.json()
 expected=[a['name'] for a in data['items'] if a['kind']=='song']
 assert expected==[a['name'] for a in data['songs']]
 return dict(slug=group['slug'],count=len(expected),first=expected[0],seconds=round(time.monotonic()-t,3))
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:api=list(pool.map(nav,groups))
by_slug={a['slug']:a for a in api}
results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(channel='chrome')
 def intercept(route):
  url=urllib.parse.urlparse(route.request.url)
  if 'navigation=true' in url.query:route.continue_()
  else:route.abort()
 for group in groups:
  item=by_slug[group['slug']]
  routes=[group['slug']+'/~album-covers',group['slug']+'/'+item['first']]
  if group.get('kind'):routes.append(group['slug'])
  for route in routes:
   context=browser.new_context();page=context.new_page();page.route('**/api/**',intercept)
   t=time.monotonic();page.goto(base+'/#/'+route,wait_until='domcontentloaded')
   try:
    page.wait_for_function("expected => document.querySelectorAll('#songs .song-row').length === expected",arg=item['count'],timeout=15000)
    links=page.locator('#songs .song-row a').evaluate_all('(links)=>links.map(a=>a.getAttribute("href"))')
    assert all(link.startswith('#/'+group['slug']+'/') for link in links)
    results.append(dict(route=route,seconds=round(time.monotonic()-t,3),count=len(links),ok=True))
   except Exception as e:results.append(dict(route=route,ok=False,error=str(e)))
   context.close()
  print('CHECKED',group['slug'],item['count'],flush=True)
 # Rapid route changes must not replace the destination list with an old response.
 context=browser.new_context();page=context.new_page();page.route('**/api/**',intercept)
 a,b=api[0],api[-1];page.goto(base+'/#/'+a['slug']+'/~album-covers',wait_until='domcontentloaded')
 page.evaluate('(slug)=>location.hash="#/"+slug+"/~album-covers"',b['slug'])
 page.wait_for_function("slug => [...document.querySelectorAll('#songs .song-row a')].length>0 && [...document.querySelectorAll('#songs .song-row a')].every(a=>a.hash.startsWith('#/'+slug+'/'))",arg=b['slug'],timeout=15000)
 page.wait_for_timeout(500)
 assert page.locator('#songs .song-row').count()==b['count']
 browser.close()
Path('work/navigation-20261115/api.json').write_text(json.dumps(api,ensure_ascii=False,indent=2))
Path('work/navigation-20261115/browser.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print('TOTAL',len(results),'FAILED',[r for r in results if not r['ok']],'MAX',max(r.get('seconds',0) for r in results),flush=True)
