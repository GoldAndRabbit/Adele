"""Retype the twelve approved Super Bowl cover designs and collection labels."""
import hashlib
import sys
from pathlib import Path

ROOT = Path('/Users/gold/repos/adele')
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, ImageOps
from workflow.live.paths import Concert, read_json, write_json
from workflow.vertical_cover import header_labels
from workflow.ai_cover import render_variants
from workflow.reviewed_cover import stage

OUT = ROOT / 'posts/bili_super_bowl_20261115'
c = Concert('singles')
plan = read_json(ROOT / 'posts/bili_full_20261114/resume-plan.json')
job = next(b for b in plan['batches'] if b['slug'] == 'super_bowl_halftime')
reviewed = {
    'next_20261031_yw7hhsr5uyy': ROOT / 'work/cover-fixes-20261114/next_20261031_yw7hhsr5uyy/stage',
    'next_20261031_jn2kgdpozz4': ROOT / 'work/cover-review-49/case-55/stage',
    'next_20261031_pilcn6vo_ru': ROOT / 'work/cover-review-49/case-54/stage',
    'next_20261031_gdsukphmb3y': ROOT / 'work/cover-review-49/case-56/stage',
}
records = []
for song in job['songs']:
    d = Path(song['path'])
    item = c.item(song['name'])
    source = read_json(d / 'post' / (d.name + '.json'))
    year = int(source['performance']['date'][:4])
    title = f'{year} 届超级碗中场秀'
    labels = header_labels(c, item)
    chinese = [s.strip() for s in labels['zh'].split(' & ')]
    english = [s.strip() for s in labels['en'].split(' & ')]
    assert len(chinese) == len(english), d.name
    credits = [' '.join(dict.fromkeys([zh, en])) for zh, en in zip(chinese[:2], english[:2])]
    subtitle = ' × '.join(credits) + ('等' if len(english) > 1 else '')
    folder = OUT / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    ai = d / 'covers/ai'
    if not (folder / 'before.json').exists():
        write_json(folder / 'before.json', {str(p): read_json(p) for p in [
            d / 'song.json', d / 'post/bili_upload.json', d / 'delivery_bundle.json',
            ai / 'masters.json', ai / 'variants.json']})
    config = read_json(d / 'song.json', {})
    config.update(cover_title=title, cover_subtitle=subtitle, collection_display_name=title)
    write_json(d / 'song.json', config)
    page = read_json(d / 'post/bili_upload.json')
    page['合集显示名称'] = title
    write_json(d / 'post/bili_upload.json', page)
    master = read_json(ai / 'masters.json')[0]
    record = dict(year=year, name=d.name, path=str(d), title=title, subtitle=subtitle,
                  master=master['file'])
    if master.get('review_hash'):
        original = reviewed[d.name]
        original_stage = read_json(original / 'stage.json')
        assert hashlib.sha256((original / 'stage.json').read_bytes()).hexdigest() == master['review_hash']
        request = dict(slug='singles', name=d.name, mode='oil', raw=original_stage['raw'],
                       input=original_stage['input'], art=str(ai / master['file']),
                       source_time=original_stage['source_time'], framing=original_stage['framing'],
                       metadata={k:v for k,v in master.items() if k != 'review_hash'})
        if original_stage.get('secondary_raw'):
            request.update(secondary_source_file=original_stage['secondary_raw'],
                           secondary_source_time=master['secondary_source_time'])
        write_json(folder / 'request.json', request)
        review_hash = stage(folder / 'request.json', folder / 'stage')
        record.update(stage=str(folder / 'stage'), review_hash=review_hash,
                      variants=read_json(folder / 'stage/stage.json')['variants'])
        record['images'] = [str(folder / 'stage' / (v['platform']+'-'+v['ratio']+'.jpg'))
                            for v in record['variants']]
    else:
        rows = render_variants(c, item, ai / master['file'], label='超级碗年份与双歌手排版')
        record.update(variants=rows, images=[str(ai / v['file']) for v in rows])
    records.append(record)
    write_json(OUT / 'prepared.json', sorted(records, key=lambda r:r['year']))
    print(year, title, subtitle, '四版已排版', flush=True)

for index in range(3):
    rows = sorted(records, key=lambda r:r['year'])[index*4:(index+1)*4]
    sheet = Image.new('RGB', (1270, 1060), '#20232a')
    draw = ImageDraw.Draw(sheet)
    for row_index, r in enumerate(rows):
        draw.text((10,row_index*265+8), str(r['year']), fill='white')
        x = 10
        for filename, width in zip(r['images'], [400,300,169,300]):
            image = Image.open(filename)
            small = ImageOps.contain(image,(width,225))
            sheet.paste(small,(x+(width-small.width)//2,row_index*265+32))
            x += width+12
    sheet.save(OUT / f'review-{index+1}.jpg',quality=95)
print('Prepared all 48 cover exports',flush=True)
