"""Update both Bilibili cover ratios while preserving the full archive copy."""
import hashlib
from pathlib import Path

import requests

from post_bili.edit_description import public_description
from post_bili.receipt import current_receipt
from post_bili.upload import bili_cookies, upload_cover
from workflow.live.paths import read_json, write_json

HEADERS = {'User-Agent': 'Mozilla/5.0',
           'Referer': 'https://member.bilibili.com/platform/upload/video/frame'}


def editor_view(aid, session=None):
    response = (session or requests).get('https://member.bilibili.com/x/vupre/web/archive/view',
                            params={'aid': aid}, cookies=bili_cookies(), headers=HEADERS, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get('code') != 0:
        raise ValueError(f"稿件编辑信息查询失败 {result.get('code')} {result.get('message', '')}")
    return result['data']


def complete_body(editor_body, candidates):
    """Only use independently recorded full text, never a creator preview."""
    candidates = {body for body in candidates if isinstance(body, str) and body}
    if editor_body in candidates:
        return editor_body
    matches = {body for body in candidates
               if len(editor_body) == 250 and len(body) > 250 and body.startswith(editor_body)}
    if len(matches) == 1:
        return matches.pop()
    raise ValueError('无法核对完整简介，保留当前线上资料')


def bfs(value):
    return (value or '').split('/bfs/')[-1]


def edit_payload(before, receipt, body):
    """Preserve current settings and both live cover ratios for metadata edits."""
    archive = before['archive']
    keys = ('aid', 'title', 'copyright', 'source', 'tid', 'dynamic', 'tag', 'interactive',
            'mission_id', 'topic_id', 'no_reprint', 'is_only_self', 'charging_pay',
            'dtime', 'upower_mode', 'upower_unit_price', 'member_first', 'cover', 'cover43')
    payload = {key:archive[key] for key in keys if key in archive}
    payload.update(desc=body, desc_format_id=9999,
                   desc_v2=[{'raw_text': body, 'type': 1, 'biz_id': ''}],
                   csrf=bili_cookies()['bili_jct'],
                   watermark={'state': before.get('watermark', {}).get('state', 0)},
                   subtitle={'open': 0, 'lan': before.get('subtitle', {}).get('lan', '')},
                   dolby=int(archive.get('is_dolby', receipt.get('dolby', 1))),
                   lossless_music=int(archive.get('lossless_music', receipt.get('lossless_music', 1))),
                   videos=[{key:v.get(key,'') for key in ('cid','filename','title','desc')}
                           for v in before['videos']])
    return payload


def sync(directory, backup):
    directory, backup = Path(directory), Path(backup)
    receipt = current_receipt(directory)
    if not receipt:
        raise ValueError('缺少当前成品版本回执')
    page = read_json(directory / 'post/bili_upload.json')
    files = {'cover': Path(page['封面16:9']), 'cover43': Path(page['封面4:3'])}
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key,path in files.items()}
    record_path = directory / 'post/cover_update.json'
    record = read_json(record_path, {})
    if record.get('source_sha256') != hashes:
        record = {'bvid': receipt['bvid'], 'source_sha256': hashes, 'uploaded': {}}
    before = editor_view(receipt['aid'])
    archive = before['archive']
    assert archive['bvid'] == receipt['bvid'] and archive['aid'] == receipt['aid']
    try:
        public = public_description(receipt['bvid'])
    except (requests.RequestException, ValueError):
        public = None
    body = complete_body(archive['desc'], [public, page['简介'], receipt.get('desc')])
    backup.mkdir(parents=True, exist_ok=True)
    original = backup / (receipt['bvid'] + '.json')
    if not original.exists():
        write_json(original, before)
    for key, file in files.items():
        if key not in record['uploaded']:
            record['uploaded'][key] = upload_cover(file)
            record['status'] = 'covers_uploaded'
            write_json(record_path, record)
    desired = record['uploaded']
    if any(bfs(archive.get(key)) != bfs(value) for key,value in desired.items()):
        payload = edit_payload(before, receipt, body)
        cookies = bili_cookies()
        payload.update(desired)
        response = requests.post('https://member.bilibili.com/x/vu/web/edit',
                                 params={'csrf':cookies['bili_jct']}, cookies=cookies,
                                 json=payload, headers=HEADERS, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            raise ValueError(f"封面更新失败 {result.get('code')} {result.get('message','')}")
        record['status'] = 'accepted_pending_verification'
        write_json(record_path, record)
    after = editor_view(receipt['aid'])
    assert after['archive']['title'] == archive['title'], '投稿标题发生变化'
    assert after['archive']['desc'] == body, '完整简介核验失败'
    assert [v['cid'] for v in after['videos']] == [v['cid'] for v in before['videos']], '视频发生变化'
    assert all(bfs(after['archive'].get(key)) == bfs(value) for key,value in desired.items()), '封面地址尚未更新'
    record.update(status='verified', description_sha256=hashlib.sha256(body.encode()).hexdigest(),
                  cover=after['archive']['cover'], cover43=after['archive']['cover43'])
    write_json(record_path, record)
    return record
