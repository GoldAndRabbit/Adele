"""Standard FIBO cover stage; scheduling uses the common HostPool.

Both consumers claim from the same list and may cross concert boundaries.
Inference and visual approval are distinct states: generation never approves
itself. A release is bound to the exact reviewed stage hash and is immediately
exported to both posting records by reviewed_cover.publish().
"""
from datetime import datetime
import fcntl
from pathlib import Path
import threading
import time
import subprocess

from workflow.ai_cover import reviewed_revision
from workflow.fibo_concert import generate_one
from workflow.live.paths import Concert, ROOT, read_json, write_json
from workflow.reviewed_cover import digest, publish, verify_release
from workflow.runtime import HostPool


def reusable_stage(base, slug, name, reviews):
    rejected = {r['review_hash'] for r in reviews.values() if r.get('status') == 'rejected'}
    candidates = sorted((base/slug/name).glob('*/attempt-*/cover-review/stage.json'),
                        key=lambda p:p.stat().st_mtime, reverse=True)
    return next((p.parent for p in candidates
                 if (p.parent/'art.png').is_file() and digest(p) not in rejected
                 and read_json(p.parent/'visual-review.json', {}).get('status') != 'rejected'), None)


def release_reviewed(directory, reviews, url):
    s = read_json(directory/'stage.json')
    key = s['slug']+'/'+s['name']
    approved = reviews.get(key, {})
    if (approved.get('status') not in {'approved', 'synced_verified'}
            or approved.get('review_hash') != digest(directory/'stage.json')):
        return False
    publish(directory, approved['review_hash'])
    # Album snapshots have a short cache. Retry verification, never inference.
    for attempt in range(4):
        try:
            verify_release(directory, s['slug'], url)
            return True
        except (OSError, ValueError):
            if attempt == 3:
                raise
            time.sleep(5)


def run(queue, model, remote_config=None, url='http://127.0.0.1:8160', auto_review=False, remote_ready=None,
        reselect_rejected=False, replace_existing=False, executor_host=None):
    directory = queue.parent
    rows = read_json(queue)
    state_file = directory/'dual-cover-status.json'
    mutex = threading.Lock()
    status = read_json(state_file, {})

    def update(key, **values):
        with mutex:
            status[key] = dict(status.get(key, {}), **values,
                               updated_at=datetime.now().astimezone().isoformat())
            write_json(state_file, status)
        print(key, values, flush=True)

    def consume(row, host):
        worker = remote_config if host not in ('local', 'primary') else None
        while worker and remote_ready and not remote_ready.exists():
            if (directory/'PAUSED').exists():
                return
            time.sleep(5)
        if (directory/'PAUSED').exists():
            return
        c = Concert(row['slug']);item = c.item(row['name'])
        key = c.slug+'/'+item['name']
        # Song locks also exclude a second coordinator using this workflow.
        slot = c.song_dir(item)/'covers/ai/.generation.lock'
        slot.parent.mkdir(parents=True, exist_ok=True)
        with slot.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                update(key, status='owned_by_another_worker')
                return
            try:
                active = reviewed_revision(slot.parent)
                # Explicit replacement keeps the old release visible until
                # the new source, AI artwork and four crops pass review.
                completed = (status.get(key, {}).get('status') == 'released_verified'
                             and active and status[key].get('review_hash') == active[0]['review_hash'])
                if active and (not replace_existing or completed):
                    record=read_json(directory/'visual-review.json',{}).get(key,{})
                    if record.get('stage') and record.get('review_hash')==active[0]['review_hash']:
                        existing=Path(record['stage']);receipt=read_json(existing/'verified.json',{})
                        if receipt.get('master')!=active[0]['file'] or receipt.get('review_hash')!=active[0]['review_hash']:
                            update(key,status='verifying_existing_release',host=host)
                            if not release_reviewed(existing,{key:record},url):
                                raise ValueError('Existing cover has no approval bound to its page verification')
                        update(key,status='released_verified')
                    else:
                        update(key,status='released')
                    return
                reviews = read_json(directory/'visual-review.json', {})
                if replace_existing:
                    # Resume this request's staged revision only. Historical
                    # approved art must not satisfy a request to reselect.
                    record = reviews.get(key, {})
                    candidate = Path(record['stage']) if record.get('stage') else None
                    staged = (candidate if candidate and record.get('status') == 'approved'
                              and (candidate/'stage.json').is_file()
                              and record.get('review_hash') == digest(candidate/'stage.json') else None)
                else:
                    staged = reusable_stage(ROOT/'work/fibo-batch', c.slug, item['name'], reviews)
                if not staged:
                    plan = read_json(c.dir/'fibo-cover-plan.json', {})
                    if replace_existing and 'replacement_source_time' not in status.get(key, {}):
                        update(key, replacement_source_time=plan.get(item['name'], {}).get('source_time'))
                    if replace_existing or (reselect_rejected and (item['name'] not in plan
                            or reviews.get(key, {}).get('status') == 'rejected'
                            or status.get(key, {}).get('status') == 'needs_repair')):
                        from workflow.fibo_reference import reselect
                        update(key, status='selecting_reference', host=host)
                        original = status.get(key, {}).get('replacement_source_time')
                        reselect(c, item, excluded_times=[original] if original is not None else [])
                        plan = read_json(c.dir/'fibo-cover-plan.json', {})
                    if item['name'] not in plan:
                        update(key, status='awaiting_reference', host=host)
                        return
                    update(key, status='generating', host=host, started_at=datetime.now().astimezone().isoformat())
                    result = generate_one(c, item, plan[item['name']], ROOT/'work/fibo-batch'/c.slug,
                                          model, worker=worker, replace_existing=replace_existing)
                    staged = Path(result['stage'])
                if auto_review and reviews.get(key, {}).get('review_hash') != digest(staged/'stage.json'):
                    from workflow.cover_visual_review import review
                    update(key, status='visual_review', host=host, stage=str(staged))
                    record = review(staged)
                    with (directory/'.visual-review.lock').open('a') as review_lock:
                        fcntl.flock(review_lock, fcntl.LOCK_EX)
                        reviews = read_json(directory/'visual-review.json', {})
                        reviews[key] = record
                        write_json(directory/'visual-review.json', reviews)
                released = release_reviewed(staged, reviews, url)
                outcome = ('released_verified' if released else
                           'visual_rejected' if reviews.get(key, {}).get('status') == 'rejected'
                           else 'awaiting_visual_review')
                update(key, status=outcome,
                       host=host, stage=str(staged), review_hash=digest(staged/'stage.json'))
            except Exception as exc:
                update(key, status='needs_repair', host=host, error=str(exc))
                # Stop a broken remote runtime after its first failure. The
                # primary keeps draining; do not load another model there.
                if worker and isinstance(exc, subprocess.SubprocessError):
                    return

    with (directory/'dual-cover.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if executor_host is not None:
            # The standard workflow already owns this machine's slot.
            for row in rows:
                consume(row, executor_host)
        else:
            hosts = ['local'] + ([read_json(remote_config)['host']] if remote_config else [])
            HostPool(hosts, paused=lambda: (directory/'PAUSED').exists()).run(rows, consume)
