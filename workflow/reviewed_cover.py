"""Stage, inspect and release a song-local cover revision.

python -m workflow.reviewed_cover stage REQUEST.json DIRECTORY
python -m workflow.reviewed_cover publish DIRECTORY --review-hash SHA256
The review sheet includes the source, actual input, mother and four final crops.
"""
import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import io
from math import gcd
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote
from urllib.request import urlopen

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from workflow.delivery_bundle import sync_cover_release
from workflow.cover_brand import BRAND_LAYOUT, has_left_brand
from workflow.ai_cover import credit_layout_version, branded_cover
from workflow.fibo_library import SIZES
from workflow.live.paths import Concert, read_json, write_json


VERSION = "source-composition-v1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compose_crop(image, size, framing):
    """Frame the reviewed lead in portrait and retain the marked span in landscape."""
    w, h = image.size
    width, height = size
    ratio = width / height
    x, y = framing['focus']
    if width < height and 'portrait_focus' in framing:
        x, y = framing['portrait_focus']
    left, right = framing.get('span', [x, x])
    if width < height:
        # Portraits fill the canvas around the lead; wide group spans apply to landscape.
        left = right = x
    if not (0 <= left <= x <= right <= 1 and 0 <= y <= 1):
        raise ValueError('Invalid subject coordinates')
    divisor = gcd(width, height)
    ratio_key = f'{width // divisor}x{height // divisor}'
    zoom = framing.get('zoom_by_ratio', {}).get(ratio_key, framing.get('zoom', 1))
    if zoom < 1:
        raise ValueError('Zoom must be at least one')
    crop_w = min(w, max(min(w, h * ratio) / zoom, (right-left) * w))
    crop_h = crop_w / ratio
    x0 = min(max(0, (x*w - crop_w/2), right*w-crop_w), left*w, w-crop_w)
    if crop_h <= h:
        anchor_y = framing.get('anchor_y_by_ratio', {}).get(ratio_key, .34)
        y0 = min(max(y*h - anchor_y*crop_h, 0), h-crop_h)
        return image.crop((round(x0), round(y0), round(x0+crop_w), round(y0+crop_h))).resize(size, Image.Resampling.LANCZOS)
    cut = image.crop((round(x0), 0, round(x0+crop_w), h))
    photo = cut.resize((width, round(h*width/crop_w)), Image.Resampling.LANCZOS)
    colors = np.asarray(cut.resize((32, 24)))
    color = tuple(int(v) for v in np.median(colors[:3].reshape(-1, 3), axis=0))
    canvas = Image.new('RGB', size, color)
    offset = round(min(height-photo.height, max(0, height*.36 - y*photo.height)))
    canvas.paste(photo, (0, offset))
    return canvas


def faithful(input_path, output, palette=None):
    """Edge-preserving source treatment. A rejected oil can contribute color only."""
    image = cv2.imread(str(input_path))
    if image is None:
        raise ValueError(f'Unreadable source: {input_path}')
    if palette:
        # Transfer the distribution of tones, never paint pixels from the other
        # image. An extra face or instrument cannot cross into the source frame.
        target = cv2.imread(str(palette))
        if target is None:
            raise ValueError(f'Unreadable color reference: {palette}')
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        style = cv2.cvtColor(target, cv2.COLOR_BGR2LAB)
        for channel, limit in enumerate((16, 7, 7)):
            src = lab[:, :, channel]
            dst = style[:, :, channel]
            # One smooth mapping per channel also preserves flat stage gradients.
            slope = np.clip(np.std(dst) / max(1., np.std(src)), .92, 1.08)
            shift = np.clip(np.mean(dst)-np.mean(src), -limit, limit)
            levels = np.arange(256)
            lut = (levels-np.mean(src))*slope + np.mean(src) + shift
            lab[:, :, channel] = cv2.LUT(src, np.rint(lut.clip(0,255)).astype('uint8'))
        image = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    base = cv2.bilateralFilter(image, 7, 27, 7)
    detail = cv2.addWeighted(base, 1.22, cv2.GaussianBlur(base, (0, 0), 1.4), -.22, 0)
    if not cv2.imwrite(str(output), detail):
        raise OSError(f'Cannot save artwork: {output}')


def shortlist(request, directory):
    """Compare three or more original frames in the final branded layouts."""
    job = read_json(request)
    concert = Concert(job['slug'])
    item = concert.item(job['name'])
    policy = read_json(concert.dir / 'vertical_source.json', {}).get('songs', {}).get(item['name'])
    if not policy:
        spec = read_json(concert.dir / 'fibo-cover-plan.json')[item['name']]
        policy = {'source': spec['source'], 'slice': spec['source_range']}
    start, end = policy['slice']
    candidates = job['candidates']
    if len({c['source_time'] for c in candidates}) < 3:
        raise ValueError('Provide three different original-frame times')
    directory.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (240*5, len(candidates)*185), '#191c24')
    draw = ImageDraw.Draw(sheet)
    records = []
    for index, candidate in enumerate(candidates):
        at = candidate['source_time']
        if not start <= at < end:
            raise ValueError(f'Candidate outside song: {at}')
        if candidate.get('frame'):
            path = Path(candidate['frame'])
        else:
            path = directory / f'frame-{index}.jpg'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(at),
                            '-i', policy['source'], '-frames:v', '1', '-q:v', '2',
                            '-y', str(path)], check=True)
        frame = Image.open(path).convert('RGB')
        preview = [frame]
        for size in SIZES.values():
            image = compose_crop(frame, size, candidate['framing'])
            preview.append(branded_cover(concert, item, image, size=size,
                           brand_scale=candidate['framing'].get('brand_scale', .70)))
        for col, image in enumerate(preview):
            small = ImageOps.contain(image, (232, 154))
            sheet.paste(small, (240*col+(240-small.width)//2, index*185))
        draw.text((6, index*185+158), f'{index+1}   song +{at-start:.2f}s')
        records.append(dict(source_time=at, song_seconds=at-start, sha256=digest(path),
                            frame=str(path.resolve()), framing=candidate['framing']))
    sheet.save(directory/'shortlist.jpg', quality=94)
    write_json(directory/'shortlist.json', records)


def oil_request(job, run):
    """Build a stage request from measured FIBO artifacts and the reviewed framing."""
    metadata = read_json(run/'master.metadata.json')
    stats = read_json(run/'master.run.json')
    timing = read_json(run/'task-time.json', {})
    original = read_json(run/'preprocess.json', {})
    return dict(job, art=str(run/'master.png'), input=str(run/'reference.png'),
                metadata=dict(model=metadata['model'], runtime='MFLUX '+metadata['mflux_version'],
                precision=metadata['precision'].split('.')[-1], label='FIBO 2.0 Edit Turbo · 油画',
                prompt=metadata['prompt'], prompt_template=original.get('prompt_template'),
                steps=metadata.get('steps'), seed=metadata.get('seed'),
                executor=metadata.get('executor'), quantization_bits=metadata.get('quantization_bits'),
                identity_reference=metadata.get('identity_reference'),
                reference_max_area=metadata.get('reference_max_area'),
                conditioning_profile=metadata.get('conditioning_profile'),
                generation_seconds=stats['generation_seconds'], elapsed_seconds=stats['elapsed_seconds'],
                peak_process_gb=round(stats['peak_process_bytes']/1e9, 2), **timing))


def stage(request, directory):
    job = read_json(request)
    if job.get('run'):
        job = oil_request(job, Path(job['run']))
    if job.get('mode') == 'oil' and (not job.get('art') or job.get('palette') or job.get('metadata', {}).get('postprocess')):
        raise ValueError('完整 AI 封面必须使用模型直接输出的母图')
    c = Concert(job['slug'])
    item = c.item(job['name'])
    marker = read_json(c.dir / 'vertical_source.json', {}).get('songs', {}).get(item['name'])
    if not marker:
        marker = read_json(c.dir / 'fibo-cover-plan.json', {}).get(item['name'], {})
    interval = marker.get('slice') or marker.get('source_range')
    if not interval or not interval[0] <= job['source_time'] < interval[1]:
        raise ValueError('Reference is outside the song')
    directory.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    started = datetime.now().astimezone().isoformat()
    raw = Path(job['raw'])
    source = Path(job['input'])
    mother = directory / 'art.png'
    meta = job.get('metadata', {}).copy()
    if job.get('palette'):
        faithful(source, mother, Path(job['palette']))
        meta['label'] = 'FIBO 色调参考 · 原帧保真'
        meta['postprocess'] = '仅迁移母图色调，人物与物件轮廓来自选定原帧'
        if job.get('foreground_oil'):
            from workflow.cover_subject_mask import painted_subject
            painted_subject(source, Path(job['palette']), mother, mother)
            meta['label'] = 'FIBO 人物油画 · 原片舞台'
            meta['postprocess'] = '只合成与原帧位置一致的油画人物，保留原片背景'
        elif job.get('preserve_stage'):
            from workflow.cover_subject_mask import on_original_stage
            on_original_stage(source, Path(job['palette']), mother, mother)
            meta['label'] = 'FIBO 笔触 · 原帧保真'
            meta['postprocess'] = '仅在原片与母图重合的人物区域提取细笔触，五官轮廓与舞台来自原片'
    elif job.get('art'):
        Image.open(job['art']).convert('RGB').save(mother)
    else:
        faithful(source, mother)
        meta.update(model='OpenCV bilateral + unsharp', runtime='OpenCV ' + cv2.__version__,
                    label='原帧保真调色', elapsed_seconds=round(time.monotonic()-start, 3),
                    started_at=started, finished_at=datetime.now().astimezone().isoformat(),
                    peak_process_gb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9, 3))
    meta['artwork_method'] = ('full_ai' if job.get('art') and not job.get('palette') else
                              'source_with_ai' if job.get('palette') else 'source_only')
    stored = 'master-' + digest(mother)[:12] + '.png'
    reference = 'references/review-' + digest(source)[:16] + source.suffix
    meta.update(file=stored, provider='local', reference=reference, source_time=job['source_time'],
                review_workflow=VERSION, source_frame_hash=digest(raw))
    rows = []
    images = []
    art = Image.open(mother).convert('RGB')
    for (platform, ratio), size in SIZES.items():
        crop = compose_crop(art, size, job['framing'])
        image = branded_cover(c, item, crop, size=size, brand_scale=job['framing'].get('brand_scale', .70),
                              credit_bottom=job['framing'].get('credit_bottom_by_ratio', {}).get(ratio))
        path = directory / (platform + '-' + ratio + '.jpg')
        image.save(path, quality=96, subsampling=0)
        filename = path.stem + '-' + digest(path)[:12] + '.jpg'
        rows.append(dict(platform=platform, ratio=ratio, file=filename, dimensions=list(size),
                         brand_layout=BRAND_LAYOUT, credit_layout=credit_layout_version(ratio), master=stored, label=meta['label'] + ' · ' + ratio.replace('x', ':')))
        images.append(image)
    sheet = Image.new('RGB', (245*7, 205), '#191c24')
    draw = ImageDraw.Draw(sheet)
    for i, (image, label) in enumerate(zip([Image.open(raw), Image.open(source), art] + images,
                     ['source', 'working input', 'art', 'Bili 16:9', 'Bili 4:3', 'Douyin 3:4', 'Douyin 4:3'])):
        small = ImageOps.contain(image, (239, 178))
        sheet.paste(small, (245*i+(245-small.width)//2, 0))
        draw.text((245*i+6, 182), label)
    sheet.save(directory/'review.jpg', quality=95)
    extra_sources = []
    if job.get('secondary_source_file'):
        other = Path(job['secondary_source_file'])
        second_time = job['secondary_source_time']
        if not interval[0] <= second_time < interval[1]:
            raise ValueError('Second reference is outside the song')
        extra_sources.append(other)
        meta['secondary_source_time'] = second_time
        meta['secondary_reference'] = 'references/source-' + digest(other)[:16] + other.suffix
    auxiliary = [Path(meta['identity_reference'])] if meta.get('identity_reference') else []
    files = {str(p.resolve()):digest(p) for p in [raw, source, mother, directory/'review.jpg', *extra_sources, *auxiliary] +
             [directory/(r['platform']+'-'+r['ratio']+'.jpg') for r in rows]}
    live = read_json(c.song_dir(item)/'covers/ai/masters.json', [])
    write_json(directory/'stage.json', dict(slug=c.slug, name=item['name'],
              expected_active=live[0]['file'] if live else None, raw=str(raw.resolve()),
              input=str(source.resolve()), source_time=job['source_time'], framing=job['framing'],
              secondary_raw=str(extra_sources[0].resolve()) if extra_sources else None,
              files=files, master=meta, variants=rows))
    return digest(directory/'stage.json')


def publish(directory, review_hash):
    manifest = directory/'stage.json'
    if digest(manifest) != review_hash:
        raise ValueError('The staged revision changed after visual review')
    s = read_json(manifest)
    for filename, expected in s['files'].items():
        if digest(Path(filename)) != expected:
            raise ValueError(f'Reviewed file changed: {filename}')
    c = Concert(s['slug'])
    ai = c.song_dir(c.item(s['name']))/'covers/ai'
    ai.mkdir(parents=True, exist_ok=True)
    (ai/'references').mkdir(exist_ok=True)
    m = dict(s['master'])
    raw = Path(s['raw'])
    m['original_reference'] = 'references/source-' + digest(raw)[:16] + raw.suffix
    with (ai/'.fibo.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_json(ai/'masters.json', [])
        active = previous[0] if previous else {}
        if ('expected_active' in s and active.get('file') != s['expected_active']
                and active.get('review_hash') != review_hash):
            raise ValueError('Active cover changed since staging. Review the current revision first.')
        variants = read_json(ai/'variants.json', [])
        if not (directory/'previous.json').exists():
            write_json(directory/'previous.json', dict(masters=previous, variants=variants))
        assets = [(directory/'art.png', ai/m['file']), (Path(s['input']), ai/m['reference']),
                  (raw, ai/m['original_reference'])]
        if s.get('secondary_raw'):
            assets.append((Path(s['secondary_raw']), ai/m['secondary_reference']))
        for v in s['variants']:
            path = directory/(v['platform']+'-'+v['ratio']+'.jpg')
            with Image.open(path) as raster:
                if not has_left_brand(raster):
                    raise ValueError(f'左上角台标或 4K 徽章未通过校验：{path}')
            v['brand_layout'] = BRAND_LAYOUT
            assets.append((path, ai/v['file']))
        for source, target in assets:
            if target.exists() and digest(target) == digest(source):
                continue
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
                with source.open('rb') as inp:
                    shutil.copyfileobj(inp, f)
            Path(f.name).replace(target)
        write_json(ai/'variants.json', [v for v in variants if v['master'] != m['file']] + s['variants'])
        write_json(ai/'masters.json', [dict(m, review_hash=review_hash)])
    sync_cover_release(c, c.item(s["name"]))
    return m['file']


def verify_release(directory, route, url):
    """Check the active album card and the four served images against reviewed bytes."""
    s = read_json(directory/'stage.json')
    master = s['master']['file']
    path = f"{url}/api/concerts/{quote(route)}"
    def fetch(endpoint):
        with urlopen(endpoint, timeout=45) as response:
            return json.load(response)
    data = fetch(path + '/songs/' + quote(s['name']) + '/cover_design')
    if not data['generated'] or data['generated'][0]['file'] != master:
        raise ValueError('UI is showing an older revision')
    served = {v['file']:v for v in data['variants'] if v['master'] == master}
    if set(served) != {v['file'] for v in s['variants']} or len(served) != 4:
        raise ValueError('UI variants differ from the reviewed set')
    for v in s['variants']:
        with urlopen(url + served[v['file']]['url'], timeout=60) as image_response:
            contents = image_response.read()
        expected_bytes = s['files'][str((directory/(v['platform']+'-'+v['ratio']+'.jpg')).resolve())]
        if hashlib.sha256(contents).hexdigest() != expected_bytes:
            raise ValueError(f"UI bytes differ from the reviewed image: {v['file']}")
        with Image.open(io.BytesIO(contents)) as image:
            if image.size != SIZES[v['platform'], v['ratio']]:
                raise ValueError(f"Unexpected image dimensions: {image.size}")
            image.verify()
    expected = next(v['file'] for v in s['variants'] if (v['platform'],v['ratio']) == ('bili-ai','16x9'))
    # A just-published song must not be checked against the previous SWR
    # snapshot, which may predate its becoming visible in the review catalog.
    card = next((r for r in fetch(path + '/album_covers?fresh=true')['covers'] if r['name'] == s['name']),None)
    if card is None:
        raise ValueError('Song is hidden or missing from the review catalog')
    if expected not in (card['url'] or ''):
        raise ValueError('Album thumbnail still points to an older cover')
    receipt = dict(review_hash=digest(directory/'stage.json'), master=master, album=card['url'],
                   formats=[(v['platform'],v['ratio'],v['dimensions']) for v in s['variants']],
                   verified_at=datetime.now().astimezone().isoformat())
    write_json(directory/'verified.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    comparison = subs.add_parser('shortlist')
    comparison.add_argument('request', type=Path)
    comparison.add_argument('directory', type=Path)
    build = subs.add_parser('stage')
    build.add_argument('request', type=Path)
    build.add_argument('directory', type=Path)
    release = subs.add_parser('publish')
    release.add_argument('directory', type=Path)
    release.add_argument('--review-hash', required=True)
    verify = subs.add_parser('verify')
    verify.add_argument('directory', type=Path)
    verify.add_argument('--route', required=True)
    verify.add_argument('--url', default='http://127.0.0.1:8160')
    args = parser.parse_args()
    if args.action == 'shortlist':
        shortlist(args.request, args.directory)
    elif args.action == 'stage':
        print(stage(args.request, args.directory))
    elif args.action == 'publish':
        print(publish(args.directory, args.review_hash))
    else:
        print(verify_release(args.directory, args.route, args.url))
