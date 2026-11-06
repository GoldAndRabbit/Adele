"""Derive four platform previews from one approved text-free AI master.

Run: python -m workflow.ai_cover concert_slug song_name /path/to/master.png
"""
import argparse
import hashlib
import shutil
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageOps
from workflow import make_cover
from workflow.live.package import cover_title, subtitle_line
from workflow.live.paths import Concert, read_json, write_json
from workflow.vertical_cover import cover_image, wide_cover, header_labels


def artwork_cover(concert, item, master, size):
    """Full-bleed artwork with title, bilingual artist and event credit."""
    canvas = ImageOps.fit(Image.open(master).convert('RGB'), size,
                          method=Image.Resampling.LANCZOS).convert('RGBA')
    width, height = size
    title = cover_title(concert, item)
    labels = header_labels(concert, item)
    artist = labels['zh'] + ' / ' + labels['en']
    title_lines = textwrap.wrap(title, width=30, break_long_words=False) if len(title) > 35 else [title]
    title_key = 'cjk_sc' if any('\u3400' <= char <= '\u9fff' for char in title) else 'cjk'
    title_font = min((make_cover.fit_width(line, title_key, int(width * .87), int(width * (.085 if len(title_lines)>1 else .12)))
                      for line in title_lines), key=lambda font: font.size)
    artist_font = make_cover.fit_width(artist, 'sub', int(width * .88), int(width * .04))
    event_font = make_cover.fit_width(labels['event'], 'sub', int(width * .88), int(width * .037))
    for index, line in enumerate(title_lines):
        baseline = height * .82 - (len(title_lines) - 1 - index) * title_font.size * 1.25
        make_cover.draw_text(canvas, (width / 2, baseline), line, title_font, stroke=.025)
    make_cover.draw_text(canvas, (width / 2, height * .89), artist, artist_font, stroke=.035)
    make_cover.draw_text(canvas, (width / 2, height * .945), labels['event'], event_font, stroke=.035)
    return canvas.convert('RGB')


def render_variants(concert, item, master, label='AI 母图试排'):
    digest = hashlib.sha256(master.read_bytes()).hexdigest()[:12]
    directory = concert.song_dir(item) / 'covers/ai'
    directory.mkdir(parents=True, exist_ok=True)
    stored = directory / ('master-' + digest + master.suffix)
    if not stored.exists():
        shutil.copyfile(master, stored)
    frame = Image.open(stored).convert('RGB')
    frame = ImageOps.fit(frame, (1920, 1080), method=Image.Resampling.LANCZOS)
    pair = make_cover.compose_pair(frame, ['--preserve-artwork', '--name', item['name'], '--title', cover_title(concert, item),
                                         '--subtitle', subtitle_line(concert, item)])
    outputs = [('bili', '16x9', pair[0]), ('bili', '4x3', pair[1]),
               ('douyin', '3x4', cover_image(concert, item, 0, pool_frame=stored, feather_edges=0)),
               ('douyin-ai', '3x4', artwork_cover(concert, item, stored, (1080, 1440))),
               ('douyin-ai', '4x3', artwork_cover(concert, item, stored, (1440, 1080)))]
    rows = []
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        temp = Path(temporary)
        wide_cover(concert, item, 0, temp / 'wide.jpg', pool_frame=stored, feather_edges=False)
        outputs.append(('douyin', '4x3', Image.open(temp / 'wide.jpg').copy()))
        for platform, ratio, image in outputs:
            pending = temp / 'render.jpg'
            image.save(pending, quality=96, subsampling=0)
            content = hashlib.sha256(pending.read_bytes()).hexdigest()[:12]
            filename = f'{platform}-{ratio}-{content}.jpg'
            pending.replace(directory / filename)
            rows.append(dict(platform=platform, ratio=ratio, dimensions=list(image.size), master=stored.name,
                             file=filename, label=label + ' · ' + {'bili':'B站', 'douyin':'抖音旧模板', 'douyin-ai':'抖音纯 AI'}[platform] + ' ' + ratio.replace('x', ':')))
        manifest = temp / 'variants.json'
        previous = read_json(directory / 'variants.json', [])
        write_json(manifest, [row for row in previous if row['master'] != stored.name] + rows)
        manifest.replace(directory / 'variants.json')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert')
    parser.add_argument('song')
    parser.add_argument('master', type=Path)
    args = parser.parse_args()
    concert = Concert(args.concert)
    for row in render_variants(concert, concert.item(args.song), args.master):
        print(row['label'], row['file'])
