"""Inspect published platform JPEGs and repair legacy corner placement from their existing master."""
import argparse
from collections import Counter
import fcntl
from pathlib import Path

from PIL import Image

from workflow.ai_cover import render_variants
from workflow.cover_brand import BRAND_LAYOUT, has_left_brand
from workflow.live.paths import CONCERTS, Concert, read_json, write_json


def check(directory, rows):
    for row in rows:
        with Image.open(directory / row['file']) as image:
            if not has_left_brand(image):
                return False
    return True


def run(report_path):
    counts = Counter()
    report = {'repaired': [], 'exceptions': [], 'missing': []}
    for setlist in sorted(CONCERTS.glob('*/setlist.json')):
        concert = Concert(setlist.parent.name)
        for item in concert.song_items():
            key = concert.slug + '/' + item['name']
            directory = concert.song_dir(item) / 'covers/ai'
            if not (directory / 'masters.json').exists():
                report['missing'].append(key)
                continue
            try:
                with (directory / '.fibo.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    masters = read_json(directory / 'masters.json', [])
                    for master in (m for m in masters if m.get('provider') == 'local'):
                        variants = read_json(directory / 'variants.json', [])
                        rows = [r for r in variants if r['master'] == master['file'] and r['platform'] in ('bili-ai','douyin-ai')]
                        if len(rows) != 4:
                            report['missing'].append(key)
                            continue
                        if not check(directory, rows):
                            if master.get('review_hash'):
                                raise ValueError('已复核裁切，需从对应复核版本重新排版')
                            rows = render_variants(concert, item, directory/master['file'], master['label'])
                            if not check(directory, rows):
                                raise ValueError('重新排版后需检查标记的实际像素')
                            report['repaired'].append(key)
                        elif any(r.get('brand_layout') != BRAND_LAYOUT for r in rows):
                            for row in rows:
                                row['brand_layout'] = BRAND_LAYOUT
                            write_json(directory/'variants.json', variants)
                        counts['masters'] += 1
                        counts['covers'] += len(rows)
            except (OSError, ValueError) as exc:
                report['exceptions'].append([key,str(exc)])
        write_json(report_path, dict(report, counts=dict(counts), last=concert.slug))
    return dict(report, counts=dict(counts))


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('report',type=Path)
    result = run(cli.parse_args().report)
    print(result['counts'], 'repaired',len(result['repaired']), 'exceptions',len(result['exceptions']))
