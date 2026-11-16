"""Derive platform previews from one approved text-free AI master.

Run: python -m workflow.ai_cover concert_slug song_name /path/to/master.png
"""
import argparse
import hashlib
import shutil
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageOps
from workflow.delivery_bundle import sync_cover_release
from workflow.cover_brand import BRAND_LAYOUT, has_left_brand
from workflow import make_cover
from workflow.live.package import compact_cover_title, cover_title, subtitle_line
from workflow.live.paths import Concert, read_json, write_json
from workflow.vertical_cover import cover_image, wide_cover, header_labels


CREDIT_LAYOUT_VERSION = "landscape-safe-credit-v3"


def credit_layout_version(ratio):
    return "douyin-safe-credit-v3" if ratio == "3x4" else CREDIT_LAYOUT_VERSION


def reviewed_revision(directory):
    """The active release owns its four individually reviewed crops."""
    masters = read_json(directory / 'masters.json', [])
    if not masters or not masters[0].get('review_hash'):
        return None
    master = masters[0]
    rows = [r for r in read_json(directory / 'variants.json', []) if r['master'] == master['file']]
    formats = {('bili-ai', '16x9'), ('bili-ai', '4x3'), ('douyin-ai', '3x4'), ('douyin-ai', '4x3')}
    if (len(rows) != 4 or {(r['platform'], r['ratio']) for r in rows} != formats
            or not all((directory / r['file']).is_file() for r in [master, *rows])):
        raise ValueError(f'视觉复核版本文件缺失，请从该曲复核记录重新发布：{directory}')
    if any(row.get('brand_layout') != BRAND_LAYOUT for row in rows):
        for row in rows:
            with Image.open(directory / row['file']) as rendered:
                if not has_left_brand(rendered):
                    raise ValueError(f'已复核封面的台标位置需要修复：{row["file"]}')
    return master, rows


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


def branded_cover(concert, item, frame, compact=True, size=(1920, 1080), crop_x=.5, brand_scale=1.0, credit_bottom=None):
    """Render a landscape cover using the song credits and the channel artwork."""
    frame = ImageOps.fit(frame, size, method=Image.Resampling.LANCZOS, centering=(crop_x, .5))
    copy = read_json(concert.song_dir(item) / 'song.json', {})
    if copy.get('cover_subtitle'):
        subtitle = copy['cover_subtitle']
    elif compact and concert.slug == 'singles':
        labels = header_labels(concert, item)
        artist = ' '.join(dict.fromkeys([labels['zh'], labels['en']]))
        subtitle = artist + ' · ' + labels['event']
    else:
        subtitle = subtitle_line(concert, item)
        if compact:
            subtitle = subtitle.rsplit(" · ", 1)[0]
    title = compact_cover_title(concert, item) if compact else cover_title(concert, item)
    args = make_cover.build_parser().parse_args([
        '--preserve-artwork', '--sub-fit', 'natural', '--name', item['name'],
        '--title', title, '--subtitle', subtitle,
    ])
    args.compact_credits = compact
    args.exact_subtitle = bool(copy.get('cover_subtitle'))
    args.brand_scale = brand_scale
    args.credit_bottom_fraction = credit_bottom
    return make_cover.compose(frame, args)


def render_variants(concert, item, master, label='AI 母图试排', *, compact=True):
    digest = hashlib.sha256(master.read_bytes()).hexdigest()[:12]
    directory = concert.song_dir(item) / 'covers/ai'
    directory.mkdir(parents=True, exist_ok=True)
    stored = directory / ('master-' + digest + master.suffix)
    reviewed = reviewed_revision(directory)
    if reviewed:
        if stored.name == reviewed[0]['file']:
            return reviewed[1]
        raise ValueError('已有复核封面，请在 reviewed_cover 中试排并提交新版本')
    if not stored.exists():
        shutil.copyfile(master, stored)
    frame = Image.open(stored).convert('RGB')
    rows = []
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        temp = Path(temporary)
        if compact:
            sizes = [('bili-ai', '16x9', (1920, 1080)), ('bili-ai', '4x3', (1440, 1080)),
                     ('douyin-ai', '3x4', (1080, 1440)), ('douyin-ai', '4x3', (1440, 1080))]
            framing = read_json(directory / 'framing.json', {}).get(stored.name, {})
            portrait = framing.get('reviewed_portrait')
            if portrait:
                from workflow.reviewed_cover import compose_crop
                portrait_frame = compose_crop(frame, (1080, 1440), portrait)
            if 'crop_box' in framing:
                box = framing['crop_box']
                frame = frame.crop(tuple(round(v * (frame.width if i % 2 == 0 else frame.height))
                                         for i, v in enumerate(box)))
            outputs = []
            for platform, ratio, size in sizes:
                if ratio == '3x4' and portrait:
                    image = branded_cover(concert, item, portrait_frame, size=size,
                                          brand_scale=portrait.get('brand_scale', .70))
                else:
                    image = branded_cover(concert, item, frame, compact=True, size=size,
                                          crop_x=framing.get(ratio, .5), brand_scale=framing.get('brand_scale', 1.0))
                outputs.append((platform, ratio, image))
        else:
            frame = ImageOps.fit(frame, (1920, 1080), method=Image.Resampling.LANCZOS)
            pair = make_cover.compose_pair(frame, ['--preserve-artwork', '--name', item['name'], '--title', cover_title(concert, item),
                                                 '--subtitle', subtitle_line(concert, item)])
            outputs = [('bili', '16x9', pair[0]), ('bili', '4x3', pair[1]),
                       ('douyin', '3x4', cover_image(concert, item, 0, pool_frame=stored, feather_edges=0)),
                       ('bili-ai', '16x9', artwork_cover(concert, item, stored, (1920, 1080))),
                       ('bili-ai', '4x3', artwork_cover(concert, item, stored, (1440, 1080))),
                       ('douyin-ai', '3x4', artwork_cover(concert, item, stored, (1080, 1440))),
                       ('douyin-ai', '4x3', artwork_cover(concert, item, stored, (1440, 1080)))]
            wide_cover(concert, item, 0, temp / 'wide.jpg', pool_frame=stored, feather_edges=False)
            outputs.append(('douyin', '4x3', Image.open(temp / 'wide.jpg').copy()))
        for platform, ratio, image in outputs:
            pending = temp / 'render.jpg'
            image.save(pending, quality=96, subsampling=0)
            if compact and not has_left_brand(image):
                raise ValueError(f"封面左上角缺少完整台标：{platform} {ratio}")
            content = hashlib.sha256(pending.read_bytes()).hexdigest()[:12]
            filename = f'{platform}-{ratio}-{content}.jpg'
            pending.replace(directory / filename)
            rows.append(dict(platform=platform, ratio=ratio, dimensions=list(image.size), master=stored.name,
                             brand_layout=BRAND_LAYOUT if compact else None,
                             credit_layout=credit_layout_version(ratio) if compact else None, file=filename, label=label + ' · ' + {'bili':'B站旧模板', 'bili-ai':'B站 AI', 'douyin':'抖音旧模板', 'douyin-ai':'抖音 AI'}[platform] + ' ' + ratio.replace('x', ':')))
        manifest = temp / 'variants.json'
        previous = read_json(directory / 'variants.json', [])
        write_json(manifest, [row for row in previous if row['master'] != stored.name] + rows)
        manifest.replace(directory / 'variants.json')
    if any(row["file"] == stored.name for row in read_json(directory / "masters.json", [])):
        sync_cover_release(concert, item)
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert')
    parser.add_argument('song')
    parser.add_argument('master', type=Path)
    parser.add_argument('--branded-output', type=Path, help='Render one branded 16:9 JPEG locally')
    parser.add_argument('--compact-credits', action='store_true', default=True, help=argparse.SUPPRESS)
    args = parser.parse_args()
    concert = Concert(args.concert)
    item = concert.item(args.song)
    if args.branded_output:
        with Image.open(args.master) as source:
            cover = branded_cover(concert, item, source.convert('RGB'), compact=args.compact_credits)
        args.branded_output.parent.mkdir(parents=True, exist_ok=True)
        cover.save(args.branded_output, format='JPEG', quality=96, subsampling=0)
    else:
        for row in render_variants(concert, item, args.master):
            print(row['label'], row['file'])
