import json,subprocess
from pathlib import Path
import pysubs2
from PIL import Image
from workflow.live.paths import Concert,read_json,write_json
from workflow.vertical_cover import header_labels
from workflow.vertical_post import posting_inputs,submission,cover_attachment
results=[]
for slug in ['grammys_2014','an_audience_with_adele_2021']:
 c=Concert(slug);rows=[]
 for it in c.song_items():
  d=c.song_dir(it);f=d/'vertical';s=read_json(d/'song.json');duration=s['slice'][1]-s['slice'][0];link=f/'original-selected.mp4'
  assert link.is_file(),(slug,it['name'],'source')
  p=json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_format','-show_streams','-of','json',str(link)]))
  assert abs(float(p['format']['duration'])-duration)<.2
  assert any(x['codec_type']=='audio' for x in p['streams'])
  caps=pysubs2.load(str(d/'subs/lyrics_poetic.ass'));lyrics=[x for x in caps if x.style=='Default' and not x.is_comment];assert lyrics
  assert all(-1<=x.start<x.end<=duration*1000+200 for x in lyrics),(it['name'],'subtitle bounds')
  picks=read_json(f/'candidates.json');assert len(picks)==18
  for r in picks:
   with Image.open(f/r['file']) as im:assert im.size==(1080,1440)
  sel=read_json(f/'selected.json',{});att=cover_attachment(d,sel.get('cover'))
  if sel:
   assert att and att.get('wide_path')
   with Image.open(att['wide_path']) as im:assert im.size==(1440,1080)
  draft,event,zh=posting_inputs(c,it,read_json(d/'post_draft.json'));post=submission(draft,event,zh);assert post['title_chars']<=30 and all(x.startswith('#') for x in post['description'].split())
  rows.append({'name':it['name'],'title':it['title'],'duration':duration,'header':header_labels(c,it),'candidates':18,'selected':bool(sel),'url':f'http://127.0.0.1:8160/#/{slug}/{it["name"]}'})
 results.append({'concert':slug,'songs':rows})
write_json('work/cover-berry/verification.json',results)
print([(r['concert'],len(r['songs'])) for r in results])
