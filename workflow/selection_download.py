"""Resumable, single-worker downloads for the selection-flow library.

State, logs, media, temporary fragments and yt-dlp's archive live on the external
volume. Cookies are read directly from Chrome and are never exported to disk.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

from workflow.selection_library import exclusion_reason
from workflow.youtube_download import cli_args

ROOT = Path(__file__).resolve().parents[1]
MIN_DURATION = 120
VERIFICATION_COOLDOWN = 5 * 60


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def folder_name(value):
    return re.sub(r'[/\\\x00-\x1f:]', '_', value).strip('. ') or 'Unknown'


def build_queue(library):
    return [dict(artist=artist['name'], artist_id=artist['id'],
                 video_id=video['video_id'], title=video['title'], url=video['url'],
                 duration_seconds=video['duration_seconds'], status='pending', attempts=0)
            for artist in library['artists'] for video in artist['videos']
            if video.get('is_song') and not exclusion_reason(video)]


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                             'stream=codec_type,codec_name,width,height,r_frame_rate:format=duration,size',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    kinds = {stream['codec_type'] for stream in info['streams']}
    if not {'video', 'audio'} <= kinds or float(info['format']['duration']) < MIN_DURATION:
        raise ValueError('Downloaded media must have video, audio and at least 120 seconds')
    return info


def download_attempt(command, log_path):
    """Classify only this attempt; an old challenge must not taint a retry."""
    with log_path.open('a') as log:
        offset = log.tell()
        code = subprocess.run(command, stdout=log, stderr=log, cwd=ROOT).returncode
    with log_path.open('rb') as log:
        log.seek(offset)
        tail = log.read().decode(errors='replace')[-12000:]
    return code, tail


def verification_action(item, tail):
    if 'sign in to confirm' not in tail.lower():
        return None
    if item.get('verification_retries', 0) == 0:
        item['verification_retries'] = 1
        return 'retry'
    return 'stop'


def run(args):
    storage = Path(json.loads((ROOT / 'external_storage.json').read_text())['root'])
    volume = Path('/Volumes') / storage.parts[2]
    if not volume.is_mount():
        raise RuntimeError(f'External volume is not mounted: {volume}')
    destination = storage / 'selection-downloads'
    job = destination / '_queue'
    job.mkdir(parents=True, exist_ok=True)
    with (job / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A selection download worker is already running')
        queue_path = job / 'queue.json'
        if queue_path.exists():
            state = json.loads(queue_path.read_text())
        else:
            library = json.loads((ROOT / 'web/selection-library.json').read_text())
            state = dict(created_at=now(), items=build_queue(library))
        resume_wait = max(0, datetime.fromisoformat(state['next_action_at']).timestamp() - time.time()) if state.get('next_action_at') else 0
        resume_reason = state.get('wait_reason') or 'scheduled wait'
        state.update(pid=os.getpid(), status='starting', error=None, updated_at=now(),
                     settings=dict(browser=args.browser, batch_size=args.batch_size,
                                   gap_seconds=[args.gap_min, args.gap_max],
                                   batch_pause_seconds=args.batch_pause,
                                   format='bestvideo+bestaudio/best', container='mkv',
                                   min_duration_seconds=MIN_DURATION,
                                   verification_cooldown_seconds=VERIFICATION_COOLDOWN,
                                   verification_retry_limit=1), destination=str(destination))
        for item in state['items']:
            if item['status'] == 'downloading':
                item['status'] = 'pending'
        def checkpoint(**updates):
            state.update(updates, updated_at=now())
            state['counts'] = dict(Counter(item['status'] for item in state['items']))
            save(queue_path, state)
        def pause(seconds, reason):
            checkpoint(status='waiting', wait_reason=reason,
                       next_action_at=datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat())
            print(f'{now()} Waiting {seconds:.0f}s: {reason}', flush=True)
            time.sleep(seconds)
        checkpoint()
        try:
            if resume_wait:
                pause(resume_wait, resume_reason)
            # Cookie/format preflight is performed before starting this worker.
            session = cli_args(state['items'][0]['url'], browser=args.browser)
            batch_count = 0
            for item in state['items']:
                if item['status'] in ('completed', 'failed', 'skipped'):
                    continue
                if not volume.is_mount():
                    raise RuntimeError('External volume disconnected')
                if shutil.disk_usage(destination).free < 20 * 1024**3:
                    raise RuntimeError('External volume has less than 20 GiB free')
                if batch_count:
                    pause(args.batch_pause if batch_count % args.batch_size == 0
                          else random.uniform(args.gap_min, args.gap_max),
                          'batch rest' if batch_count % args.batch_size == 0 else 'between videos')
                artist_dir = destination / folder_name(item['artist'])
                artist_dir.mkdir(exist_ok=True)
                log_path = job / (item['video_id'] + '.log')
                receipt = job / (item['video_id'] + '.path')
                command = [sys.executable, '-m', 'yt_dlp', *session,
                           '--no-playlist', '--continue', '--no-overwrites', '--no-progress',
                           '--concurrent-fragments', '1', '--sleep-requests', '2',
                           '--retries', '3', '--fragment-retries', '3',
                           '--retry-sleep', 'http:exp=5:60', '--retry-sleep', 'fragment:exp=5:60',
                           '--socket-timeout', '30', '--abort-on-unavailable-fragments',
                           '--match-filters', 'duration >= 120',
                           '--download-archive', str(job / 'download-archive.txt'),
                           '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mkv',
                           '-P', str(artist_dir), '-P', f'temp:{artist_dir}',
                           '-o', '%(title).160B [%(id)s].%(ext)s',
                           '--print-to-file', 'after_move:%(filepath)s', str(receipt),
                           '--no-simulate', item['url']]
                run_attempts = 0
                verification_retry_due = False
                while run_attempts < 3 or verification_retry_due:
                    verification_retry_due = False
                    run_attempts += 1
                    item.update(status='downloading', attempts=item['attempts'] + 1, started_at=now())
                    checkpoint(status='downloading', current=dict(artist=item['artist'], title=item['title'], video_id=item['video_id']),
                               next_action_at=None, wait_reason=None)
                    print(f"{now()} Downloading {item['artist']}: {item['title']}", flush=True)
                    code, tail = download_attempt(command, log_path)
                    if code == 0 and receipt.exists():
                        path = Path(receipt.read_text().splitlines()[-1])
                        try:
                            media = probe(path)
                            item.update(status='completed', finished_at=now(), path=str(path), media=media)
                            checkpoint()
                            print(f"{now()} Completed {item['video_id']}", flush=True)
                            break
                        except (ValueError, OSError, subprocess.CalledProcessError) as error:
                            item['error'] = str(error)
                    if code == 0 and 'does not pass filter' in tail:
                        item.update(status='skipped', error='Source duration below 120 seconds')
                        checkpoint()
                        break
                    challenge = verification_action(item, tail)
                    if challenge:
                        item['status'] = 'pending'
                        if challenge == 'retry':
                            verification_retry_due = True
                            pause(VERIFICATION_COOLDOWN, 'YouTube verification cooldown before one automatic retry')
                            continue
                        checkpoint(status='needs_verification', error='YouTube bot-verification challenge persisted after a 5-minute cooldown and one retry; user action required')
                        return
                    if any(value in tail.lower() for value in ('cookies are no longer valid', 'login required')):
                        item['status'] = 'pending'
                        checkpoint(status='needs_login', error='YouTube explicitly requires a refreshed login')
                        return
                    limited = any(value in tail.lower() for value in ('429', 'too many requests', 'rate-limit', 'rate limit'))
                    if run_attempts < 3:
                        item['status'] = 'pending'
                        pause(1800 * run_attempts if limited else 300 * run_attempts,
                              'YouTube rate limit' if limited else 'download retry backoff')
                    else:
                        item.update(status='failed', error=f'Download or verification failed; see {log_path.name}')
                        checkpoint()
                batch_count += 1
                # Stop a run of repeated failures instead of hammering the service.
                recent = [row['status'] for row in state['items'] if row['status'] in ('completed', 'failed')]
                if recent[-3:] == ['failed'] * 3:
                    checkpoint(status='needs_attention', error='Three consecutive downloads failed')
                    return
            checkpoint(status='complete_with_errors' if any(i['status'] == 'failed' for i in state['items']) else 'completed', current=None)
        except BaseException as error:
            checkpoint(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'needs_attention', error=str(error))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', default='chrome:Default')
    parser.add_argument('--batch-size', type=int, default=5)
    parser.add_argument('--gap-min', type=int, default=60)
    parser.add_argument('--gap-max', type=int, default=120)
    parser.add_argument('--batch-pause', type=int, default=600)
    args = parser.parse_args()
    if args.batch_size < 1 or args.gap_min < 0 or args.gap_max < args.gap_min or args.batch_pause < 0:
        parser.error('Invalid batch or interval settings')
    run(args)


if __name__ == '__main__':
    main()
