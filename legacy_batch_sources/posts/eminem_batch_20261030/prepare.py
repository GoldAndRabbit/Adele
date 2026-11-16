from pathlib import Path
import json
import requests
import sys

ROOT = Path('/Users/gold/repos/adele')
sys.path.insert(0, str(ROOT))
from workflow.live.paths import Concert, write_json
from workflow.live.setlist import parse

BATCH = ROOT / 'posts/eminem_batch_20261030'
slug = 'eminem_detroit_anger_management'
c = Concert(slug)
c.dir.mkdir(parents=True, exist_ok=True)
source_name = '_eminem_detroit_concert_source'
url = 'https://www.youtube.com/watch?v=0aVfL_4_NLw'
raw = json.loads(Path('/tmp/adele_eminem_concert_metadata.json').read_text())
source = ROOT / 'posts' / source_name
source.mkdir(exist_ok=True)
keys = ('title','channel','duration','language','track','artist','upload_date','description','tags','webpage_url')
write_json(source / 'meta.json', {k: raw.get(k) for k in keys})
write_json(c.info, {'slug':slug, 'source_file':str(source / 'source.mp4'), 'source_url':url,
                  'artist':'Eminem', 'artist_zh':'埃米纳姆',
                  'title':'Eminem · Live from Detroit · Anger Management Tour 2', 'city':'Detroit',
                  'duration':raw['duration'], 'notes':'2023 是上传视频版本标签，不用作演出日期；边界来自用户及原视频简介，待审核。'})
tracks = [
('0:38','Square Dance','Eminem'),('3:56','Business','Eminem'),('6:29','White America','Eminem'),
('9:28','Kill You','Eminem'),('11:20','When the Music Stops','Eminem'),('17:05','Pimp Like Me','D12'),
('18:45','Fight Music','D12'),('20:56','Purple Pills','D12'),('25:25','The Way I Am','Eminem'),
('28:43','Soldier','Eminem'),('31:37',"Cleanin’ Out My Closet",'Eminem'),('34:24','Forgot About Dre','Dr. Dre'),
('36:05','Drips','Eminem'),('42:39','Superman','Eminem'),('45:42','Drug Ballad','Eminem'),
('48:41',"Just Don’t Give a Fuck",'Eminem'),('51:56','Without Me','Eminem'),('58:02',"My Dad’s Gone Crazy",'Eminem')]
text = '# 来源：用户给定时间点，与原视频简介一致；歌词使用标准曲名\n' + '\n'.join(f'{title} | {artist} | 用户时间点 {time}' for time,title,artist in tracks)+'\n'
c.setlist_txt.write_text(text)
items = parse(text,'Eminem')
write_json(c.setlist, {'source':'user + YouTube description', 'items':items})
def secs(t):
    m,s=map(int,t.split(':'));return m*60+s
segments=[]
for i,(it,(t,title,artist)) in enumerate(zip(items,tracks)):
    c.make_song_dir(it)
    segments.append({'idx':it['idx'],'name':it['name'],'title':it['title'],'kind':'song',
                     'start':secs(t),'end':secs(tracks[i+1][0]) if i+1<len(tracks) else raw['duration'],
                     'manual':True,'confidence':0.5,'flags':['用户/视频简介时间点，待检查前奏、尾奏、讲话与过场']})
write_json(c.segments, {'items':segments, 'gaps':[{'start':0,'end':38,'interludes':['开场'],'talk':[]}],
                        'source':'user timestamps; provisional cuts'})
singles = [
('eminem_real_slim_shady_y8zi1uc6ibm','Y8ZI1uc6iBM',['The Real Slim Shady'],'Eminem',''),
('eminem_lose_yourself_hd','_Yhyp-_hX2s',['Lose Yourself'],'Eminem',''),
('eminem_real_slim_shady_mv_clean','eJO5HU_7_1w',['The Real Slim Shady'],'Eminem','标题标明 Clean Version，字幕按实际演唱核对，不补出未唱的脏话。'),
('eminem_stan_long_mv','gOMhN-hfMtY',['Stan'],'Eminem','标题为 Long Version，含 Dido。'),
('eminem_monster_mv','EHkozMIXZ8w',['The Monster'],'Eminem','标题注明 Rihanna 参与。'),
('eminem_houdini_mv','22tVWwmTie8',['Houdini'],'Eminem',''),
('eminem_rap_god_mv','XbGs_qK2PQA',['Rap God'],'Eminem','标题标明 Explicit。'),
('eminem_lose_yourself_oscars2020','Cbtgk20s6wA',['Lose Yourself'],'Eminem','标题注明第 92 届奥斯卡 2020 现场。'),
('eminem_rap_god_rrhof2022','ZAf-oiqQhmc',['Rap God'],'Eminem','标题注明 2022 Rock & Roll Hall of Fame 现场。'),
('eminem_love_way_lie_radio1','h_-JFUci0BM',['Love the Way You Lie'],'Eminem','BBC Radio 1 视频，标题注明 Skylar Grey 参与。'),
('eminem_love_way_lie_not_afraid_vmas2010','Ul-b1-ar0p0',['Love the Way You Lie','Not Afraid'],'Eminem','MTV 标题注明 2010 VMAs，Eminem 与 Rihanna，串烧按实际顺序和演唱部分对齐。'),
]
manifest = {'concert':{'slug':slug,'source_name':source_name,'url':url},'singles':[]}
with requests.Session() as session:
 for name,vid,parts,artist,note in singles:
    link='https://www.youtube.com/watch?v='+vid
    r=session.get('https://www.youtube.com/oembed',params={'url':link,'format':'json'},timeout=30);r.raise_for_status()
    data=r.json()
    d=ROOT/'posts'/name;d.mkdir(exist_ok=True)
    write_json(d/'source_oembed.json',data)
    manifest['singles'].append({'name':name,'url':link,'parts':parts,'artist':artist,'source_title':data['title'],
                                'note':f"原视频标题：{data['title']}；频道：{data.get('author_name','')}。{note}"})
write_json(BATCH/'manifest.json',manifest)
print('Prepared',slug,':',len(items),'concert songs and',len(singles),'singles')
