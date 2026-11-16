"""Apply an approved title plan to exactly the current 378 rendered archives."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import fcntl
import hashlib
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from post_bili.edit_cover import bfs, editor_view
from post_bili.edit_description import redacted_error
from post_bili.edit_title import sync
from post_bili.receipt import current_receipt
from workflow.bili_title import VERSION, concert_directory
from workflow.live.paths import read_json, write_json


class PacedSession(requests.Session):
    def __init__(self, interval):
        super().__init__()
        self.interval = interval
        self.last_request = 0

    def request(self, *args, **kwargs):
        delay = self.interval - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        return super().request(*args, **kwargs)


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')


def eligible_rows(records, results, current=None):
    """Rotate deferred checks instead of letting one uncertain edit block all."""
    current=current or datetime.now(ZoneInfo('Asia/Shanghai'))
    rows=[]
    for row in records:
        result=results.get(row['bvid'],{})
        if result.get('status')=='verified':
            continue
        due=result.get('next_verify_after')
        if not due and result.get('status')=='pending_verification' and result.get('checked_at'):
            due=(datetime.fromisoformat(result['checked_at'])+timedelta(minutes=30)).isoformat()
        if due and current<datetime.fromisoformat(due):
            continue
        rows.append(row)
    return sorted(rows,key=lambda row:results.get(row['bvid'],{}).get('checked_at',''))


def edit_was_rejected(error):
    return '412 Client Error' in error and '/x/vu/web/edit' in error


def manifest(source, folder):
    path = folder / 'manifest.json'
    if path.exists():
        plan = read_json(path)
        if plan['rule_version'] != VERSION:
            raise ValueError('规则已变化，不能在旧计划上继续提交')
        return plan
    review = read_json(source)
    rows = [r for r in review['records'] if r.get('scope') == '本次成片']
    assert len(rows) == len({r['bvid'] for r in rows}) == 378
    records = []
    for row in rows:
        d = Path(row['local_path'])
        receipt = current_receipt(d)
        assert receipt and receipt['bvid'] == row['bvid'], '当前成片与BV绑定发生变化'
        decision = review.get('decisions', {}).get(row['bvid'], {})
        title = (decision.get('final') if decision.get('decision') == '手工改写' else
                 row['before'] if decision.get('decision') == '保留原样' else row['proposed'])
        assert title and len(title) <= 80
        records.append({'bvid':row['bvid'], 'aid':receipt['aid'], 'path':str(d), 'title':title,
                        'snapshot_title':row['online_title'], 'original_title':row['before'],
                        'note':row.get('note',''), 'receipt':receipt})
    records.sort(key=lambda r: (0 if r['bvid'] == 'BV1XesL6aEQ7' else
                               1 if r['title'] != r['snapshot_title'] else 2, r['bvid']))
    plan = {'created_at':now(), 'rule_version':VERSION, 'total':378,
            'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(), 'records':records}
    write_json(path, plan)
    return plan


def verify_only(row, folder, http):
    bv = row['bvid']
    proof_path = folder / 'online-title-updates' / (bv + '.json')
    proof = read_json(proof_path)
    if not proof:
        raise ValueError('没有已提交记录，不能当作已修改')
    baseline = read_json(folder / 'online-before' / (bv + '.json'))
    after = editor_view(row['aid'], session=http)
    a, b = after['archive'], baseline['archive']
    assert a['bvid'] == bv and a['aid'] == row['aid']
    expected_desc = proof.get('authorized_description_sha256') or proof['description_sha256']
    assert hashlib.sha256(a['desc'].encode()).hexdigest() == expected_desc, '完整简介发生变化'
    assert all(bfs(a.get(k)) == bfs(b.get(k)) for k in ('cover','cover43')), '线上封面发生变化'
    assert [v['cid'] for v in after['videos']] == [v['cid'] for v in baseline['videos']], '视频发生变化'
    if a['title'] != row['title']:
        return {**proof, 'status':'pending_verification', 'observed_title':a['title'], 'checked_at':now(),
                'next_verify_after':(datetime.now(ZoneInfo('Asia/Shanghai'))+timedelta(minutes=30)).isoformat()}
    proof.update(status='verified', verified_at=now(), cover=a.get('cover'), cover43=a.get('cover43'),
                 cids=[v['cid'] for v in after['videos']])
    write_json(proof_path, proof)
    return proof


def save_progress(folder, plan, results):
    counts = Counter(r['status'] for r in results.values())
    result = {'updated_at':now(), 'total':plan['total'], 'checked':len(results), 'counts':dict(counts),
              'changed_verified':sum(r.get('changed',False) and r['status']=='verified' for r in results.values()),
              'unchanged_verified':sum(not r.get('changed',False) and r['status']=='verified' for r in results.values()),
              'verification_modes':dict(Counter(r.get('verification_mode','full_archive')
                                                for r in results.values() if r['status']=='verified')),
              'remaining':plan['total']-counts.get('verified',0), 'records':results}
    write_json(folder / 'progress.json', result)
    return result


def verify_no_edit_titles(plan, results, folder, snapshot):
    """A matching title needs no write; don't require editing access for it."""
    titles = {}
    for line in Path(snapshot).read_text().splitlines():
        cols = line.split('\t')
        if len(cols) >= 2 and cols[0].startswith('BV'):
            titles[cols[0]] = cols[1]
    count = 0
    for row in plan['records']:
        bv = row['bvid']
        if (row['title'] != row['snapshot_title'] or titles.get(bv) != row['title']
                or (folder/'online-title-updates'/(bv+'.json')).exists()
                or results.get(bv,{}).get('status') == 'verified'):
            continue
        results[bv] = {'bvid':bv, 'aid':row['aid'], 'title':row['title'], 'changed':False,
                       'status':'verified', 'verification_mode':'creator_list_no_edit',
                       'protected_fields_not_written':True, 'checked_at':now(),
                       'source_snapshot':Path(snapshot).name}
        count += 1
    save_progress(folder,plan,results)
    return count


def pin_local(plan, results, folder):
    """Pin the approved titles without rebuilding descriptions or covers."""
    backup = folder / 'local-before'
    backup.mkdir(exist_ok=True)
    count = 0
    for row in plan['records']:
        if results.get(row['bvid'],{}).get('status') != 'verified':
            continue
        directory = Path(row['path'])
        rp = concert_directory(directory) / 'review.json'
        rev = read_json(rp, {})
        bp = backup / (rp.parent.name + '-review.json')
        if not bp.exists():
            write_json(bp, rev)
        entry = rev.setdefault('songs',{}).setdefault(directory.name,{})
        if entry.get('title') and entry['title'] != row['title']:
            raise ValueError('人工标题已发生变化，不覆盖：' + directory.name)
        entry['title'] = row['title']
        write_json(rp,rev)
        pp = directory / 'post/bili_upload.json'
        page = read_json(pp)
        bp = backup / (row['bvid'] + '-bili_upload.json')
        if not bp.exists():
            write_json(bp,page)
        old_desc = page.get('简介')
        old_covers = [page.get(k) for k in ('封面16:9','封面4:3')]
        page.update(标题=row['title'], 标题字符数=len(row['title']))
        write_json(pp,page)
        saved = read_json(pp)
        assert saved.get('简介') == old_desc
        assert [saved.get(k) for k in ('封面16:9','封面4:3')] == old_covers
        count += 1
    write_json(folder / 'local-title-sync.json', {'updated_at':now(), 'count':count,
                                                'fields':['review.songs.title','bili_upload.标题','bili_upload.标题字符数']})
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--pin-local', action='store_true')
    parser.add_argument('--interval', type=float, default=1.2)
    args = parser.parse_args()
    args.folder.mkdir(parents=True,exist_ok=True)
    with (args.folder / '.title-sync.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = manifest(args.source,args.folder)
        if not args.submit and not args.verify_only:
            print('checked plan:',len(plan['records']),'current archives; no online changes')
            return
        results = read_json(args.folder / 'progress.json', {}).get('records',{})
        verified_before = {bv for bv,result in results.items() if result.get('status')=='verified'}
        attempted = 0
        query_failures = 0
        with PacedSession(args.interval) as http:
            for row in eligible_rows(plan['records'],results):
                bv = row['bvid']
                if results.get(bv,{}).get('status') == 'verified':
                    continue
                if args.limit is not None and attempted >= args.limit:
                    break
                attempted += 1
                try:
                    receipt = current_receipt(Path(row['path']))
                    assert receipt and receipt['bvid'] == bv and receipt['aid'] == row['aid'], '成片回执绑定发生变化'
                    proof = read_json(args.folder / 'online-title-updates' / (bv+'.json'),{})
                    if args.verify_only or proof.get('status') in ('submitting','accepted_pending_verification','pending_verification'):
                        result = verify_only(row,args.folder,http)
                        # A recorded HTTP 412 rejected the edit before acceptance.
                        # Confirm the original is still present before retrying.
                        if (args.submit and not args.verify_only and proof.get('status') == 'submitting'
                                and edit_was_rejected(results.get(bv,{}).get('error',''))
                                and result.get('observed_title') == proof.get('before_title')):
                            result = sync(row['path'],row['title'],args.folder,receipt=receipt,session=http)
                    else:
                        result = sync(row['path'],row['title'],args.folder,receipt=receipt,session=http)
                    if result.get('status')=='pending_verification':
                        original_error=results.get(bv,{}).get('submission_error') or results.get(bv,{}).get('error')
                        if original_error:
                            result['submission_error']=original_error
                    results[bv] = result
                    query_failures = 0
                except AssertionError as exc:
                    message = redacted_error(exc)
                    if '标题回读' in message:
                        results[bv] = {**read_json(args.folder/'online-title-updates'/(bv+'.json'),{}),
                                       'status':'pending_verification','error':message,'checked_at':now()}
                    else:
                        results[bv] = {'status':'preservation_check_failed','error':message,'checked_at':now()}
                        save_progress(args.folder,plan,results)
                        raise
                except Exception as exc:
                    prior = read_json(args.folder/'online-title-updates'/(bv+'.json'),{})
                    results[bv] = {**prior,'status':'pending_verification' if prior.get('status') in
                                   ('submitting','accepted_pending_verification') else 'needs_retry',
                                   'error':redacted_error(exc)[:300], 'checked_at':now()}
                    if '412' in str(exc) or isinstance(exc, requests.ConnectionError):
                        query_failures += 1
                progress = save_progress(args.folder,plan,results)
                print(f"{bv} {results[bv]['status']} verified={progress['counts'].get('verified',0)}/378 updated={progress['changed_verified']}",flush=True)
                if any(code in results[bv].get('error','') for code in ('412 Client Error',' -702')) or query_failures >= 3:
                    print('paused for connection/query cooldown',flush=True)
                    break
        if args.pin_local:
            local_plan = plan
            if args.limit is not None:
                local_plan = {**plan,'records':[r for r in plan['records'] if r['bvid'] not in verified_before
                                               and results.get(r['bvid'],{}).get('status')=='verified']}
            if local_plan['records']:
                print('local titles pinned:',pin_local(local_plan,results,args.folder),flush=True)
        final = save_progress(args.folder,plan,results)
        print('SUMMARY', {k:v for k,v in final.items() if k != 'records'},flush=True)


if __name__ == '__main__':
    main()
