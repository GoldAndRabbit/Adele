"""Synchronize a corrected description while preserving the archive's media."""
import json
import hashlib
import subprocess
import re
from pathlib import Path

import requests

from post_bili.receipt import current_receipt
from post_bili.upload import bili_cookies, ROOT
from workflow.live.paths import read_json, write_json


def redacted_error(error):
    return re.sub(r"(?i)((?:csrf|access_key|bili_jct|sessdata|api_key)=)[A-Za-z0-9._~%+/-]+",
                  r"\1[redacted]", str(error))


def show(bvid):
    output = subprocess.check_output(
        [ROOT / "bin/biliup", "-u", ROOT / "post_bili/cookies.json", "show", bvid],
        cwd=ROOT, timeout=25, stderr=subprocess.PIPE)
    return json.loads(output)


def public_description(bvid):
    with requests.Session() as session:
        response = session.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid},
                               cookies=bili_cookies(), headers={"User-Agent": "Mozilla/5.0",
                               "Referer": "https://www.bilibili.com/"}, timeout=15)
        response.raise_for_status()
        result = response.json()
    if result.get("code") in (-404, 62002):
        return None
    if result.get("code") != 0:
        raise ValueError(f"公开简介查询失败 {result.get('code')}")
    return result["data"]["desc"]


def sync(directory, backup):
    directory = Path(directory)
    receipt = current_receipt(directory)
    if not receipt:
        return False
    page = read_json(directory / "post/bili_upload.json")
    bvid = receipt["bvid"]
    record_path = directory / "post/description_update.json"
    return sync_archive(bvid, page["简介"], receipt, record_path, backup)


def sync_web(directory, body, folder, *, expected_before_sha256, session=None):
    """Correct approved text using the full web editor, retaining both covers."""
    from post_bili.edit_cover import HEADERS, bfs, edit_payload, editor_view
    directory, folder = Path(directory), Path(folder)
    receipt = current_receipt(directory)
    if not receipt:
        raise ValueError('缺少当前成片回执')
    if not body.strip() or len(body) > 2000:
        raise ValueError('简介必须为1–2000字符')
    before = editor_view(receipt['aid'], session=session)
    archive = before['archive']
    assert archive['bvid'] == receipt['bvid'] and archive['aid'] == receipt['aid']
    assert archive.get('state') != -100, '稿件已删除'
    old_hash = hashlib.sha256(archive['desc'].encode()).hexdigest()
    new_hash = hashlib.sha256(body.encode()).hexdigest()
    if old_hash not in (expected_before_sha256, new_hash):
        raise ValueError('线上简介已有其他修改，不能覆盖')
    folder.mkdir(parents=True, exist_ok=True)
    bp = folder / 'online-before.json'
    if not bp.exists():
        write_json(bp, before)
    record = {'bvid':receipt['bvid'], 'aid':receipt['aid'], 'title':archive['title'],
              'before_description_sha256':expected_before_sha256, 'description_sha256':new_hash,
              'description_chars':len(body), 'status':'submitting'}
    rp = folder / 'online-description-update.json'
    if old_hash != new_hash:
        previous = read_json(rp,{})
        if previous.get('status') in ('submitting','accepted_pending_verification'):
            raise ValueError('已提交的简介尚未回读一致，本次只核验，不重复提交')
        payload = edit_payload(before, receipt, body)
        cookies = bili_cookies()
        write_json(rp,record)
        response = (session or requests).post('https://member.bilibili.com/x/vu/web/edit',
                            params={'csrf':cookies['bili_jct']}, cookies=cookies, json=payload,
                            headers=HEADERS, timeout=30)
        if response.status_code == 412:
            record.update(status='rejected_before_acceptance',http_status=412)
            write_json(rp,record)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            record.update(status='rejected_before_acceptance',error_code=result.get('code'))
            write_json(rp,record)
            raise ValueError(f"简介纠错失败 {result.get('code')} {result.get('message','')}")
        record['status'] = 'accepted_pending_verification'
        write_json(rp,record)
        after = editor_view(receipt['aid'],session=session)
    else:
        after = before
    assert after['archive']['title'] == archive['title'], '标题发生变化'
    assert after['archive']['desc'] == body, '完整简介尚未回读一致'
    assert all(bfs(after['archive'].get(k)) == bfs(archive.get(k)) for k in ('cover','cover43')), '封面发生变化'
    assert [v['cid'] for v in after['videos']] == [v['cid'] for v in before['videos']], '视频发生变化'
    record.update(status='verified',cover=after['archive'].get('cover'),cover43=after['archive'].get('cover43'),
                  cids=[v['cid'] for v in after['videos']])
    write_json(rp,record)
    return record


def sync_archive(bvid, body, receipt, record_path, backup, *, only_if_truncated=False):
    record_path = Path(record_path)
    record_path.parent.mkdir(exist_ok=True)
    expected_hash = hashlib.sha256(body.encode()).hexdigest()
    try:
        published = public_description(bvid)
    except (requests.RequestException, ValueError):
        published = None
    if published == body:
        write_json(record_path, {"bvid": bvid, "description_sha256": expected_hash, "status": "verified"})
        return True
    if not only_if_truncated and published is None and receipt.get("desc") == body:
        write_json(record_path, {"bvid": bvid, "description_sha256": expected_hash,
                                "description_chars": len(body), "status": "submitted_pending_verification"})
        return False
    if only_if_truncated:
        if published is None:
            write_json(record_path, {"bvid": bvid, "status": "waiting_for_public_copy"})
            return False
        if len(published) != 250 or not body.startswith(published):
            write_json(record_path, {"bvid": bvid, "status": "preserved_current_description",
                                     "remote_chars": len(published)})
            return False
    previous = read_json(record_path, {})
    if (previous.get("description_sha256") == expected_hash
            and previous.get("status") == "accepted_pending_verification"):
        return False
    before = show(bvid)
    archive = before["archive"]
    if archive.get("state") == -100:
        raise ValueError("稿件已下架，不能同步简介")
    if receipt.get("aid") and archive["aid"] != receipt["aid"]:
        raise ValueError("回执与线上稿件不匹配")
    if archive["desc"] != body:
        backup = Path(backup)
        backup.mkdir(exist_ok=True)
        if not (backup / (bvid + ".json")).exists():
            write_json(backup / (bvid + ".json"), before)
        keys = ("aid", "copyright", "source", "tid", "desc_v2", "dynamic", "tag",
                "interactive", "mission_id", "no_reprint", "is_only_self", "charging_pay", "cover")
        cookies = bili_cookies()
        payload = {k: archive[k] for k in keys if k in archive}
        payload.update(title=archive["title"], desc=body, desc_format_id=9999,
                       desc_v2=[{"raw_text": body, "type": 1, "biz_id": ""}],
                       csrf=cookies["bili_jct"], subtitle={"open": 0, "lan": ""},
                       dolby=int(receipt.get("dolby", 1)), lossless_music=int(receipt.get("lossless_music", 1)),
                       watermark={"state": int(receipt.get("watermark", 0))},
                       videos=[{k: v.get(k, "") for k in ("cid", "filename", "title", "desc")}
                               for v in before["videos"]])
        response = requests.post("https://member.bilibili.com/x/vu/web/edit",
                                 params={"csrf": cookies["bili_jct"]}, cookies=cookies, json=payload,
                                 headers={"User-Agent": "adele-workflow/1.0",
                                          "Referer": "https://member.bilibili.com/platform/upload/video/frame"},
                                 timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise ValueError(f"简介同步失败 {result.get('code')} {result.get('message', '')}")
        write_json(record_path, {"bvid": bvid, "description_sha256": expected_hash,
                                "description_chars": len(body), "status": "accepted_pending_verification"})
    after = show(bvid)
    assert after["archive"]["title"] == archive["title"], "标题发生变化"
    assert after["archive"]["cover"] == archive["cover"], "封面发生变化"
    assert [v["cid"] for v in after["videos"]] == [v["cid"] for v in before["videos"]], "视频发生变化"
    # Creator archive endpoints return a 250-character preview; that preview
    # must never be mistaken for the full description or used for restoration.
    try:
        verified = public_description(bvid) == body
    except (requests.RequestException, ValueError):
        verified = False
    write_json(record_path, {"bvid": bvid, "description_sha256": expected_hash,
                            "description_chars": len(body),
                            "status": "verified" if verified else "accepted_pending_verification",
                            "state": after["archive"].get("state_desc")})
    return verified
