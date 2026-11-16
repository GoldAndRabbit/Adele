import json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from workflow.live.paths import Concert,slugify,write_json
rows={2025:[
('I Love L.A.','Dawes & John Legend & Sheryl Crow & Brad Paisley & Brittany Howard & St. Vincent','道斯乐队 & 约翰·传奇 & 雪莉·克劳 & 布拉德·佩斯利 & 布兰妮·霍华德 & 圣文森特','Randy Newman'),
('Birds of a Feather','Billie Eilish & Finneas','碧莉·艾莉许 & 菲尼亚斯','Billie Eilish'),
('Espresso / Please Please Please','Sabrina Carpenter','莎布丽娜·卡彭特','Sabrina Carpenter'),
('Pink Pony Club','Chappell Roan','查普尔·罗恩','Chappell Roan'),
('May Ninth','Khruangbin','克鲁昂宾乐队','Khruangbin'),
('Beautiful Things','Benson Boone','本森·布恩','Benson Boone'),
('Catfish / Denial Is a River','Doechii','多伊奇','Doechii'),
('Lose Control','Teddy Swims','泰迪·斯威姆斯','Teddy Swims'),
('Good News / A Bar Song (Tipsy)','Shaboozey','沙布泽','Shaboozey'),
('Oscar Winning Tears','RAYE','蕾伊','RAYE'),
("California Dreamin'",'Lady Gaga & Bruno Mars','嘎嘎小姐 & 布鲁诺·马尔斯','The Mamas & the Papas'),
('Cry for Me / Timeless','The Weeknd & Playboi Carti','威肯 & Playboi Carti','The Weeknd'),
('Killer Joe / Fly Me to the Moon / Let the Good Times Roll / Bluesette / We Are the World / Don’t Stop ’Til You Get Enough','Herbie Hancock & Cynthia Erivo & Lainey Wilson & Jacob Collier & Stevie Wonder & Janelle Monáe','赫比·汉考克 & 辛西娅·艾莉佛 & 莱妮·威尔逊 & 雅各布·科利尔 & 史蒂维·旺德 & 加奈儿·梦奈',None),
('All My Love','Chris Martin & Grace Bowers','克里斯·马汀 & 格蕾丝·鲍尔斯','Coldplay'),
('Ojos Así / Shakira: Bzrp Music Sessions, Vol. 53','Shakira','夏奇拉','Shakira'),
('Von Dutch / Guess','Charli XCX','查莉·XCX','Charli XCX')],2026:[
('APT.','ROSÉ & Bruno Mars','朴彩英 & 布鲁诺·马尔斯','ROSÉ'),
('Manchild','Sabrina Carpenter','莎布丽娜·卡彭特','Sabrina Carpenter'),
('No One Noticed','The Marías','玛丽亚乐队','The Marías'),
('Fame Is a Gun','Addison Rae','艾迪森·蕾','Addison Rae'),
('Gnarly','KATSEYE','KATSEYE', 'KATSEYE'),
('Mutt','Leon Thomas','里昂·托马斯','Leon Thomas'),
('Ordinary','Alex Warren','亚历克斯·沃伦','Alex Warren'),
('Messy','Lola Young','萝拉·杨','Lola Young'),
('Man I Need','Olivia Dean','奥利维娅·迪恩','Olivia Dean'),
('12 to 12','sombr','sombr','sombr'),
('Yukon','Justin Bieber','贾斯汀·比伯','Justin Bieber'),
('Abracadabra','Lady Gaga','嘎嘎小姐','Lady Gaga'),
('I Just Might','Bruno Mars','布鲁诺·马尔斯','Bruno Mars'),
('Thought I Was Dead / Like Him / Sugar on My Tongue','Tyler, the Creator','造物主泰勒','Tyler, the Creator'),
('Trailblazer','Reba McEntire & Brandy Clark & Lukas Nelson','瑞芭·麦肯泰尔 & 布兰迪·克拉克 & 卢卡斯·尼尔森','Reba McEntire'),
('War Pigs','Post Malone & Slash & Duff McKagan & Chad Smith & Andrew Watt','波兹·马龙 & 斯拉什 & 达夫·麦卡根 & 查德·史密斯 & 安德鲁·瓦特','Black Sabbath'),
('Nothing Even Matters / Brown Sugar / Lady / Devil’s Pie / Another Life / Untitled (How Does It Feel) / Africa / The First Time Ever I Saw Your Face / Compared to What / The Closer I Get to You / Where Is the Love / Feel Like Makin’ Love / Killing Me Softly with His Song / Total Praise','Lauryn Hill & Friends','劳伦·希尔与嘉宾',None),
('So Far Ahead','Clipse & Pharrell Williams & Voices of Fire','克利普斯组合 & 法瑞尔·威廉姆斯 & 火焰之声合唱团','Clipse') ]}
base=Path('/Volumes/harddisk_5T/adele-workflow/posts')
for y,entries in rows.items():
 c=Concert(f'grammys_{y}');real=base/c.slug;real.mkdir(parents=True,exist_ok=True)
 link=Path('posts')/c.slug
 if not link.exists():link.symlink_to(real)
 items=[]
 for idx,(title,artist,zh,lookup) in enumerate(entries,1):
  it=dict(idx=idx,name=f'{idx:02d}_{slugify(title)}',title=title,artist=artist,artist_zh=zh,kind='song',parts=title.split(' / '),notes='medley' if ' / ' in title else '',lyrics_lookup_artist=lookup,review_hidden=True,ingest_status='awaiting_source_boundaries')
  items.append(it);d=c.make_song_dir(it)
  write_json(d/'song.json',it)
  info=c.load('info')
  write_json(d/'post_draft.json',{'song':{'title':title,'artist':artist,'artist_zh':zh},'performance':{'event':info['title'],'event_en':info['title_en'],'date':info['date']},'intro':{},'tags':[],'metadata_origin':'broadcast credits; initial inventory, pending source verification'})
 write_json(c.setlist,{'items':items,'reference':f'https://en.wikipedia.org/wiki/{67 if y==2025 else 68}th_Annual_Grammy_Awards','status':'pending_broadcast_boundary_validation'})
 (c.setlist_txt).write_text('\n'.join(f'{t} | {a} | medley' if ' / ' in t else f'{t} | {a}' for t,a,z,l in entries)+'\n')
 print(y,len(items),'initial blocks; hidden until source boundaries checked')
