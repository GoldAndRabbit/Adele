"""Repair only short descriptions and expired schedules for the requested Chile batch."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path('/Users/gold/repos/adele')
sys.path[:0] = [str(ROOT), str(ROOT / 'workflow')]
from workflow.live.paths import Concert, read_json, write_json
from workflow import make_meta
from workflow.delivery_bundle import write_bundle
from post_bili.upload import check, from_page

OUT = ROOT / 'work/bili-four-concerts-20261116'
C = Concert('lorde_lolla_chile2026')
FROZEN = ('标题', '封面16:9', '封面4:3', '标签', '视频文件')


def prepare(item):
    directory = C.song_dir(item)
    backup = OUT / 'metadata-before' / item['name']
    backup.mkdir(parents=True, exist_ok=True)
    for name in ('post/bili_upload.json', 'post_draft.json', 'delivery_bundle.json'):
        value = read_json(directory / name)
        target = backup / name.replace('/', '--')
        if value is not None and not target.exists():
            write_json(target, value)
    page = read_json(directory / 'post/bili_upload.json')
    original = {key: page[key] for key in FROZEN}
    schedule = page.get('定时发布')
    if schedule and datetime.strptime(schedule, '%Y-%m-%d %H:%M').timestamp() < datetime.now().timestamp() + 14400:
        page['定时发布'] = ''
        write_json(directory / 'post/bili_upload.json', page)
        print('EXPIRED_SCHEDULE_CLEARED', item['name'], flush=True)
    if len(page['简介']) < 1800:
        draft = read_json(directory / 'post_draft.json')
        candidate = OUT / 'intro-candidates' / (item['name'] + '.json')
        gen = read_json(candidate)
        if gen is None:
            user = ('补齐这首已有歌曲投稿简介。只写材料支持的事实与分析，不新增发行日期、榜单成绩、数字、嘉宾、'
                    '舞台道具或服装等事实。歌词只做中文转述，不引用原文；不要引用舞台画面帧编号。'
                    '保留原稿的歌曲、现场、歌词三部分的主题，补充有意义的分析，避免重复与空话。\n'
                    + json.dumps({'演出资料': read_json(C.info), '曲目': item,
                                  '原稿': draft, '歌曲资料': read_json(directory / 'song.json', {})}, ensure_ascii=False))
            user += make_meta.media_material(read_json(directory / 'stage_notes.json'),
                        make_meta.lyrics_material(directory / 'lyrics.txt', directory / 'zh_cache.json'))
            gen = make_meta.generate_intro(user, label='智利投稿简介 ' + item['name'])
            candidate.parent.mkdir(parents=True, exist_ok=True)
            write_json(candidate, gen)
        draft['intro'] = {key: gen['intro_' + key] for key in ('song', 'performance', 'lyrics')}
        draft['intro_text'] = make_meta.intro_text(gen)
        write_json(directory / 'post_draft.json', draft)
        write_bundle(C, item)
        page = read_json(directory / 'post/bili_upload.json')
        # Keep the user's completed title, video and cover selections exactly.
        page.update(original)
        write_json(directory / 'post/bili_upload.json', page)
        bundle = read_json(directory / 'delivery_bundle.json')
        bundle['bilibili'].update(original)
        write_json(directory / 'delivery_bundle.json', bundle)
    spec, errors = check(from_page(page))
    result = dict(song=item['name'], status='ready' if not errors else 'needs_attention',
                  description_length=len(page['简介']), errors=errors, spec=spec)
    print('PREFLIGHT', json.dumps(result, ensure_ascii=False), flush=True)
    return result


def safe_prepare(item):
    try:
        return prepare(item)
    except (Exception, SystemExit) as error:
        result = dict(song=item['name'], status='needs_attention', error=str(error))
        print('PREPARE_ERROR', json.dumps(result, ensure_ascii=False), flush=True)
        return result


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(safe_prepare, C.song_items()))
write_json(OUT / 'chile-preflight.json', results)
print('CHILE_READY', sum(row['status'] == 'ready' for row in results), len(results), flush=True)
