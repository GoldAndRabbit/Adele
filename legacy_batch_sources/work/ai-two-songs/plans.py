from pathlib import Path
import json,shutil
from PIL import Image,ImageOps,ImageDraw
from workflow.live.paths import Concert
c=Concert('grammys_2014');pol=json.loads((c.dir/'vertical_source.json').read_text())['songs']
sets={'01_drunk_in_love':[(122,'霓虹人像','清晰的正面半身特写，紫蓝灯光与湿发造型可辨。'),(82,'烟雾座椅','人物居中坐于椅子，烟雾与舞台构成环境全身图。'),(194,'双人同台','碧昂丝与Jay-Z均可辨认，保留合作演出的语境。')], '02_royals':[(51,'侧面人像','自然三分之二侧脸，睁眼，面部与演出白上衣可辨。'),(124,'演唱半身','居中的正面半身演唱动作，白上衣和星点背光。'),(182,'星光舞台','歌手全身居中，保留鼓组、伴奏人员与舞台灯阵。')]}
common='Create a refined painterly oil painting of this exact live musical performance, using the supplied unlettered original video frame as the sole primary reference. Maintain the recognizable real performer facial identity, exact number of foreground performers, same costumes, hair, natural anatomy, hands, microphone and stage relationship. Keep the original concert palette and lighting, using nuanced oil brushwork and rich but natural color, no monochrome conversion. Do not change the camera angle or invent extra people. Remove TV station logos and all lettering. No text, captions, typography, numbers, logos, watermarks or badges. Compose a full-bleed 16:9 artwork with the main subject heads and torsos inside the central 42 percent width so the same artwork can safely crop to 4:3 and 3:4. Keep meaningful background across the whole image and leave the bottom quarter visually calm for later local title overlay. Do not add borders, empty bars or collages. Preserve faces clearly; retain the real scene rather than glamorizing or changing the performer.'
for name,rows in sets.items():
 d=c.song_dir(c.item(name))/'covers/ai';refs=d/'references';refs.mkdir(parents=True,exist_ok=True);candidates=[];contact=Image.new('RGB',(1280,600*3),(25,25,25));draw=ImageDraw.Draw(contact)
 for i,(t,label,why) in enumerate(rows):
  f=refs/f'ts-{pol[name]["slice"][0]+t:.4f}.jpg';shutil.copy2(Path('work/ai-two-songs')/name/f'fine-{t}.jpg',f)
  for j,(w,h) in enumerate([(480,270),(360,270),(300,400)]):
   im=ImageOps.fit(Image.open(f),(w,h));contact.paste(im,(j*450,i*600));draw.text((j*450,i*600+410),f'{label} | {w}:{h}',fill='white')
  extra=' Both Beyonce and Jay-Z must remain together in the central crop; retain their distinct identities and clothes.' if name.startswith('01') and t==194 else ''
  candidates.append({'label':label,'reference':'references/'+f.name,'source_time':pol[name]['slice'][0]+t,'relative_time':t,'selection_reason':why,'composition_distinction':label,'reference_role':'primary scene and identity','prompt':common+extra})
 contact.save(Path('work/ai-two-songs')/name/'crop-check.jpg')
 plan={'strategy':'ai-cover-frame-selection-v1','source':pol[name]['source'],'source_range':pol[name]['slice'],'coarse_sampling_seconds':6,'style':'same oil painting, original scene palette','review':'manual scene and crop inspection; user adoption pending','candidates':candidates}
 (d/'seedream-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2));print(name,str(d/'seedream-plan.json'))
