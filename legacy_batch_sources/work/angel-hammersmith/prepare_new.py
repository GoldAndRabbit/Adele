from compare import *
from workflow.live.paths import write_json,read_json
from workflow.song.title_translation import save
from shutil import copyfile
src=Path('posts/the_angel_live');d=Path('posts/the_angel_hammersmith_5gu277dbf8i');n=d.name
title='天使（永远的北伦敦）';song=read_json(src/'post/the_angel_live.json')['song'];record={'title':song['title'],'title_zh':title,'artist_zh':'路易斯·邓福德','source':'复用同曲两版已核对译名'};save(d,record)
for f in ('lyrics.txt','lyrics_source'):copyfile(src/f,d/f)
units=lines('the_angel_live').values()
fixed={u['orig']:u['v2_final'] for u in units if u['locked']};fixed['__title__']=title;write_json(d/'zh_fixed.json',fixed)
write_json(d/'post'/f'{n}.json',{'name':n,'song':song,'performance':{'event':'Live From Hammersmith','event_en':'Live From Hammersmith','event_zh':'哈默史密斯现场','date':'2023'},'source':{'url':'https://www.youtube.com/watch?v=5gU277dBf8I','channel':'Louis Dunford','title':'Louis Dunford - The Angel (North London Forever) (Live From Hammersmith)'},'performance_sources':['https://www.withguitars.com/louis-dunford-to-release-new-ep-and-extra-dates-for-live-acoustic-tour-this-summer/'],'intro':{'performance':'路易斯·邓福德在伦敦哈默史密斯 Eventim Apollo 演唱《天使（永远的北伦敦）》。'},'tags':['Louis Dunford','North London Forever','哈默史密斯现场','中英字幕']})
