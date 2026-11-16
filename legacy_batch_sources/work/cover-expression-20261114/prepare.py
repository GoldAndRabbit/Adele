from workflow.live.paths import *
from workflow.reviewed_cover import compose_crop
from PIL import Image
import subprocess
b=ROOT/'work/cover-expression-20261114';jobs=[];policy=read_json(Concert('singles').dir/'vertical_source.json')['songs']
for n,t,fr,note in [
('adele_send_my_love_mv_fk4bbf7b29w',25.5,dict(focus=[.55,.24],zoom=1.55),'Adele alone, facing the camera in the original floral dress with her hands resting together. Keep the original swept-up hair, open eyes and relaxed brow. Her mouth is calm, with a subtle small closed-lip smile. Preserve her real facial proportions and natural lip thickness. The backdrop is a featureless near-black wash, with absolutely no extra faces, figures, instruments or double-exposure images.'),
('adele_rolling_in_deep_mv_ryeda3jcqqw',79.9,dict(focus=[.43,.27],zoom=1.10),'Adele alone in the original black dress, seated before the pale folded fabric. Preserve the exact face proportions, naturally open eyes, swept-up hair, camera angle and dress. Gently relax the tense singing mouth into a small, warm, natural closed-lip smile. Keep her lips thin and proportional, with relaxed cheeks and brow; no pouting, enlarged glossy lips, grimace, wide-open mouth or exaggerated teeth. The pale draped fabric stays softly indistinct, with no other people or added scenery.')]:
 d=b/n;d.mkdir(exist_ok=True);raw=d/'selected.jpg';subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',policy[n]['source'],'-frames:v','1','-q:v','2','-y',str(raw)],check=True)
 prompt='Paint this reference as a luminous, full-bleed fine oil painting. '+note+' Retain her unmistakable likeness, real hand positions and all clothing. Use delicate restrained brushstrokes on the face and broader painterly strokes on large shapes. No lettering, watermarks, logos or graphics.'
 write_json(d/'selection.json',dict(slug='singles',source_time=t,raw=str(raw.resolve()),scene_note=note,prompt_override=prompt,run='run1',pre_model_framing=fr))
 subprocess.run(['.venv/bin/python','workflow/fibo_cover.py',str(raw),str(d/'run1'),'--prompt',prompt],check=True)
 inp=d/'run1/reference.png';im=Image.open(inp).convert('RGB');im.save(d/'run1/cleaned-full.png');compose_crop(im,(768,432),fr).save(inp);meta=read_json(d/'run1/preprocess.json');meta['pre_model_framing']=fr;write_json(d/'run1/preprocess.json',meta)
 jobs.append(dict(slug='singles',name=n,run=str((d/'run1').resolve()),prompt=prompt))
write_json(b/'batch-jobs.json',jobs)
