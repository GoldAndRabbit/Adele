"""Change only an archive title and verify full copy, live covers and media."""
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from post_bili.edit_cover import HEADERS, bfs, complete_body, edit_payload, editor_view
from post_bili.edit_description import public_description
from post_bili.receipt import current_receipt
from post_bili.upload import bili_cookies
from workflow.bili_title import VERSION
from workflow.live.paths import read_json, write_json


def sync(directory, title, folder, *, receipt=None, session=None):
    directory, folder = Path(directory), Path(folder)
    receipt = receipt or current_receipt(directory)
    if not receipt:
        raise ValueError('缺少明确的投稿回执，不能按同名稿件推测修改')
    if not title.strip() or len(title) > 80:
        raise ValueError('标题必须为1–80字符')
    http = session or requests
    before = editor_view(receipt['aid'], session=session)
    archive = before['archive']
    assert archive['bvid'] == receipt['bvid'] and archive['aid'] == receipt['aid']
    if archive.get('state') == -100:
        raise ValueError('稿件已删除，保留记录，不尝试修改')
    page = read_json(directory / 'post/bili_upload.json', {})
    candidates = [page.get('简介'), receipt.get('desc')]
    try:
        body = complete_body(archive['desc'], candidates)
    except ValueError:
        candidates.append(public_description(receipt['bvid']))
        body = complete_body(archive['desc'], candidates)
    original = folder / 'online-before' / (receipt['bvid'] + '.json')
    original.parent.mkdir(parents=True, exist_ok=True)
    if not original.exists():
        write_json(original, before)
    record_path = folder / 'online-title-updates' / (receipt['bvid'] + '.json')
    record_path.parent.mkdir(exist_ok=True)
    record = {'bvid':receipt['bvid'], 'aid':receipt['aid'], 'song':directory.name,
              'title':title, 'before_title':archive['title'], 'rule_version':VERSION,
              'description_sha256':hashlib.sha256(body.encode()).hexdigest(),
              'changed': archive['title'] != title}
    if archive['title'] != title:
        payload = edit_payload(before, receipt, body)
        payload['title'] = title
        if archive.get('desc_v2'):
            payload['desc_v2'] = archive['desc_v2']
            payload['desc_format_id'] = archive.get('desc_format_id', 9999)
        cookies = bili_cookies()
        record['status'] = 'submitting'
        write_json(record_path, record)
        response = http.post('https://member.bilibili.com/x/vu/web/edit',
                             params={'csrf':cookies['bili_jct']}, cookies=cookies,
                             json=payload, headers=HEADERS, timeout=30)
        if response.status_code == 412:
            record['status'] = 'rejected_before_acceptance'
            write_json(record_path, record)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            record.update(status='rejected_before_acceptance', error_code=result.get('code'))
            write_json(record_path, record)
            raise ValueError(f"标题更新失败 {result.get('code')} {result.get('message','')}")
        record['status'] = 'accepted_pending_verification'
        write_json(record_path, record)
        after = editor_view(receipt['aid'], session=session)
    else:
        after = before
    assert after['archive']['title'] == title, '标题回读不一致'
    assert after['archive']['desc'] == body, '完整简介发生变化'
    assert all(bfs(after['archive'].get(key)) == bfs(archive.get(key))
               for key in ['cover','cover43']), '线上封面发生变化'
    assert [v['cid'] for v in after['videos']] == [v['cid'] for v in before['videos']], '视频发生变化'
    record.update(status='verified', verified_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                  cover=after['archive'].get('cover'), cover43=after['archive'].get('cover43'),
                  cids=[v['cid'] for v in after['videos']])
    write_json(record_path, record)
    return record
