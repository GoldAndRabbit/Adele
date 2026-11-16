from run import *
from workflow.song import song_translation_workflow as W
from workflow.live.refine import sub_title
from workflow.song.title_translation import save
slug,name=sys.argv[1:3]
c=Concert(slug);it=c.item(name);d=c.song_dir(it);out=d/'subs'
units=W.load_units(out);uni=list(dict.fromkeys(u['orig'] for u in units))
if len(sys.argv)==3:
 for i,v in enumerate(uni):print(i,v)
else:
 zh=sys.argv[3];vals=(BASE/slug/(name+'.zh.txt')).read_text().splitlines()
 assert len(vals)==len(uni),(len(vals),len(uni))
 translations=dict(zip(uni,vals))
 for u in units:
  v=translations[u['orig']]
  u.update(v1=v,v2=v,v3=v,issues=[])
 save(d,dict(title=it['title'],title_zh=zh,artist_zh=it.get('artist_zh'),reason='按本次现场歌词译名，待审核'))
 r=dict(model='Codex',version='local-review-draft',title=sub_title(c,it),title_zh='《'+zh+'》',units=units,notes={},brief={})
 write_json(out/'translation/result.json',r);W.build_outputs(d,out)
 from workflow.song.title_translation import sync
 sync(d)
