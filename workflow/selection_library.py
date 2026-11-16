"""Refresh the selection-flow snapshot from each channel's actual Popular button.

Run: .venv/bin/python -m workflow.selection_library
Only public video metadata is requested; no videos are downloaded.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

CHANNELS = [
    ('TaylorSwift', 'Taylor Swift'), ('LadyGaga', 'Lady Gaga'),
    ('Lorde', 'Lorde'), ('adele', 'Adele'), ('TheWeeknd', 'The Weeknd'),
    ('rihanna', 'Rihanna'), ('KatyPerry', 'Katy Perry'), ('Shakira', 'Shakira'),
    ('beyonce', 'Beyoncé'), ('HKT48', 'HKT48'),
    ('OneRepublic', 'OneRepublic'), ('kendricklamar', 'Kendrick Lamar'),
    ('OliviaRodrigo', 'Olivia Rodrigo'), ('justinbieber', 'Justin Bieber'),
    ('EdSheeran', 'Ed Sheeran'), ('BTS', 'BTS'),
    ('BadBunnyPR', 'Bad Bunny'), ('DrakeOfficial', 'Drake'),
    ('brunomars', 'Bruno Mars'), ('DuaLipa', 'Dua Lipa'),
    ('BillieEilish', 'Billie Eilish'), ('ArianaGrande', 'Ariana Grande'),
    ('BLACKPINK', 'BLACKPINK'), ('sza', 'SZA'),
    ('sabrinacarpenter', 'Sabrina Carpenter'), ('ChappellRoan', 'Chappell Roan'),
    ('LinkinPark', 'Linkin Park'),
]
LIMIT = 25
SOURCE_LIMIT = 50
MIN_DURATION_SECONDS = 120
NON_SONG = re.compile(
    r'\b(interview|behind the scenes|behind-the-scenes|making of|making the|'
    r'trailer|teaser|documentary|q\s*&\s*a|in conversation|vlog|announcement|'
    r'backstage|sneak peek|commencement speech|burn the stage ep\s*\d+)\b', re.I,
)

# Audio uploads whose channel titles omit the Audio label.
AUDIO_VIDEO_IDS = {'V2G8ESoDXm8', 'zSLLyBci-EI'}
NON_SONG_VIDEO_IDS = {'xR55tIcWNVg'}  # Chappell Roan: documentary episode
LYRIC_OR_AUDIO = re.compile(r'\b(?:lyrics?|audio)\b|歌詞|歌词|리릭|오디오', re.I)


def exclusion_reason(video):
    if not video['is_song'] or video.get('video_id') in NON_SONG_VIDEO_IDS:
        return 'non_song'
    if video['duration_seconds'] < MIN_DURATION_SECONDS:
        return 'shorter_than_120_seconds'
    if LYRIC_OR_AUDIO.search(video['title']) or video.get('video_id') in AUDIO_VIDEO_IDS:
        return 'lyric_or_audio'
    return None


def select_videos(videos):
    selected, excluded = [], []
    for video in videos[:SOURCE_LIMIT]:
        video.pop('exclusion_reason', None)
        reason = exclusion_reason(video)
        if reason:
            video['exclusion_reason'] = reason
            excluded.append(video)
        elif len(selected) < LIMIT:
            selected.append(video)
    return selected, excluded


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def text(value):
    return value.get('simpleText') or ''.join(run['text'] for run in value.get('runs', []))


def parse_videos(response):
    videos = []
    seen = set()
    for item in walk(response):
        if 'lockupViewModel' in item:
            video = item['lockupViewModel']
            if video.get('contentType') != 'LOCKUP_CONTENT_TYPE_VIDEO':
                continue
            video_id = video['contentId']
            title = video['metadata']['lockupMetadataViewModel']['title']['content']
            badges = [d['thumbnailBadgeViewModel'].get('text', '') for d in walk(video.get('contentImage', {})) if 'thumbnailBadgeViewModel' in d]
            duration = next((t for t in badges if re.fullmatch(r'\d+(?::\d{2}){1,2}', t)), '')
            metadata = video['metadata']['lockupMetadataViewModel'].get('metadata', {})
            views = next((d['accessibilityLabel'] for d in walk(metadata) if 'view' in d.get('accessibilityLabel', '').lower()), '')
        elif 'videoRenderer' in item:
            video = item['videoRenderer']
            video_id = video['videoId']
            title = text(video['title'])
            duration = text(video.get('lengthText', {}))
            views = text(video.get('viewCountText', {}))
        else:
            continue
        if video_id in seen:
            continue
        seen.add(video_id)
        if not duration or not views:
            raise ValueError(f'Missing duration/views for {title}')
        parts = [int(part) for part in duration.split(':')]
        seconds = sum(part * 60 ** i for i, part in enumerate(reversed(parts)))
        videos.append(dict(rank=len(videos) + 1, video_id=video_id, title=title,
                           url=f'https://www.youtube.com/watch?v={video_id}',
                           duration=duration, duration_seconds=seconds,
                           views=views, is_song=not bool(NON_SONG.search(title))))
    return videos


def fetch_artist(channel):
    handle, name = channel
    url = f'https://www.youtube.com/@{handle}/videos'
    session = requests.Session()
    page = session.get(url, params={'hl': 'en'}, timeout=60)
    page.raise_for_status()
    html = page.text
    decoder = json.JSONDecoder()
    initial = decoder.raw_decode(html.split('var ytInitialData = ', 1)[1])[0]
    configs = []
    for match in re.finditer(r'ytcfg.set\(', html):
        try:
            configs.append(decoder.raw_decode(html[match.end():])[0])
        except ValueError:
            pass
    config = next(c for c in configs if 'INNERTUBE_CONTEXT' in c)
    chip = next(d['chipViewModel'] for d in walk(initial) if d.get('chipViewModel', {}).get('text') == 'Popular')
    command = chip['tapCommand']['innertubeCommand']
    response = session.post('https://www.youtube.com/youtubei/v1/browse', json={
        'context': config['INNERTUBE_CONTEXT'],
        'continuation': command['continuationCommand']['token'],
    }, timeout=60)
    response.raise_for_status()
    popular = response.json()
    assert any(d.get('chipViewModel', {}).get('text') == 'Popular' and d['chipViewModel'].get('selected') for d in walk(popular)), 'Popular selection not confirmed'
    videos = []
    seen = set()
    while True:
        for video in parse_videos(popular):
            if video['video_id'] in seen:
                continue
            seen.add(video['video_id'])
            video['rank'] = len(videos) + 1
            videos.append(video)
        if len(videos) >= SOURCE_LIMIT:
            break
        continuation = next((d['continuationItemRenderer'].get('continuationEndpoint', {})
                             .get('continuationCommand', {}).get('token')
                             for d in walk(popular) if 'continuationItemRenderer' in d), None)
        if not continuation:
            break
        time.sleep(2)
        response = session.post('https://www.youtube.com/youtubei/v1/browse', json={
            'context': config['INNERTUBE_CONTEXT'], 'continuation': continuation,
        }, timeout=60)
        response.raise_for_status()
        popular = response.json()
    videos = videos[:SOURCE_LIMIT]
    if len(videos) < SOURCE_LIMIT:
        raise ValueError(f'{name}: expected {SOURCE_LIMIT} Popular videos, got {len(videos)}')
    selected, excluded = select_videos(videos)
    print(f'{name}: scanned {len(videos)}, selected {len(selected)}, excluded {len(excluded)}', flush=True)
    for video in selected:
        print(f"  {video['rank']:2} {video['title']} | {video['duration']}", flush=True)
    return dict(id=handle, name=name, channel_url=url, popular_limit=SOURCE_LIMIT,
                selection_limit=LIMIT, source_videos=videos,
                videos=selected, excluded_videos=excluded)


def fetch_with_retry(channel):
    for attempt in range(3):
        try:
            return fetch_artist(channel)
        except (requests.RequestException, IndexError, StopIteration) as error:
            if attempt == 2:
                raise
            print(f'{channel[0]}: retry after {type(error).__name__}', flush=True)
            time.sleep(10 * (attempt + 1))


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        artists = list(pool.map(fetch_with_retry, CHANNELS))
    snapshot = dict(fetched_date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),
                    sort='Popular', popular_limit=SOURCE_LIMIT, selection_limit=LIMIT, min_duration_seconds=MIN_DURATION_SECONDS, artists=artists)
    output = Path(__file__).resolve().parents[1] / 'web' / 'selection-library.json'
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(output)
    print(f'Saved {sum(len(a["videos"]) for a in artists)} songs to {output}')


if __name__ == '__main__':
    main()
