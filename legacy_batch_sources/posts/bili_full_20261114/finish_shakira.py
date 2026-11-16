import sys,json,time,requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path.cwd()))
from workflow.live.paths import read_json,write_json
from post_bili.batch import season_edit,season
from post_bili.upload import bili_cookies
folder=Path(__file__).parent
row=read_json(folder/'shakira-collection-detail.json')
season_edit('edit',{'season':{**row['season'],'no_section':0},'sorts':[{'id':10727035,'sort':1}]})
job=read_json(folder/'plan.json')['batches'][0]
def episode(song):
 d=Path(song['path']);r=read_json(d/'post/publish.json');p=read_json(d/'post/bili_upload.json')
 j=requests.get('https://api.bilibili.com/x/web-interface/view',params={'bvid':r['bvid']},cookies=bili_cookies(),headers={'User-Agent':'adele-workflow/1.0','Referer':'https://www.bilibili.com/'},timeout=30).json()
 if j.get('code')!=0:raise ValueError((song['name'],j.get('code')))
 return {'aid':r['aid'],'cid':j['data']['cid'],'title':p['合集显示名称']}
with ThreadPoolExecutor(max_workers=3) as pool:episodes=list(pool.map(episode,job['songs']))
season_edit('section/episodes/add',{'sectionId':10727035,'episodes':episodes})
result=requests.get('https://member.bilibili.com/x2/creative/web/season/section',params={'id':10727035},cookies=bili_cookies(),headers={'User-Agent':'adele-workflow/1.0','Referer':'https://member.bilibili.com/'},timeout=30).json()
write_json(folder/'shakira-final-section.json',result)
print('合集已加入',len(result['data']['episodes']),flush=True)
