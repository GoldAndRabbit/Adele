import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
p=Path('work/local-flux3')
fibo=p/'royals-fibo2-turbo.png'
flux=p/'royals-bf16.png'
meta=[json.loads(f.with_suffix('.metadata.json').read_text()) for f in (flux,fibo)]
for k in ('seed','width','height','prompt','image_paths'):
    assert meta[0][k]==meta[1][k], k
assert meta[1]['steps']==4 and meta[1]['quantize'] is None
images=[Path(meta[1]['image_paths'][0]),flux,fibo]
labels=['原片参考','FLUX 3 Klein · BF16','FIBO 2.0 Edit Turbo · BF16']
canvas=Image.new('RGB',(2320,490),'#191c22'); draw=ImageDraw.Draw(canvas)
font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',26)
for i,(path,label) in enumerate(zip(images,labels)):
    with Image.open(path) as im:
        im=ImageOps.contain(im.convert('RGB'),(768,432),Image.Resampling.LANCZOS)
        x=776*i
        canvas.paste(im,(x,56));draw.text((x+10,12),label,font=font,fill='white')
canvas.save(p/'royals-flux-fibo.comparison.jpg',quality=96)
