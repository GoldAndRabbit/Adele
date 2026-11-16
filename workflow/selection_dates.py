"""Cache YouTube publication dates without downloading or modifying any videos."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'web/selection-dates.json'


def publication_date(html):
    patterns = [r'"publishDate"\s*:\s*"(\d{4}-\d{2}-\d{2})[^"<]*"',
                r'<meta\b[^>]*itemprop="datePublished"[^>]*content="(\d{4}-\d{2}-\d{2})[^"<]*"',
                r'"uploadDate"\s*:\s*"(\d{4}-\d{2}-\d{2})[^"<]*"']
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return date.fromisoformat(match[1]).isoformat()
    match = re.search(r'"publishDate"\s*:\s*\{\s*"simpleText"\s*:\s*"([^"<]+)"', html)
    if match:
        for format in ('%b %d, %Y', '%B %d, %Y'):
            try:
                return datetime.strptime(match[1], format).date().isoformat()
            except ValueError:
                continue
    raise ValueError('YouTube page did not include a publication date')


class YouTubeRateLimited(RuntimeError):
    pass


def fetch_date(video_id):
    url = f'https://www.youtube.com/watch?v={video_id}'
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=(10, 25))
            if response.status_code == 429:
                raise YouTubeRateLimited('YouTube is rate limiting metadata requests; stopped, rerun later to resume')
            response.raise_for_status()
            return {'date': publication_date(response.text), 'source': url}
        except (requests.RequestException, ValueError):
            if attempt == 2:
                return {'date': None, 'source': url, 'status': 'unavailable'}
            time.sleep(attempt + 1)


def refresh():
    library = json.loads((ROOT / 'web/selection-library.json').read_text())
    ids = list(dict.fromkeys(v['video_id'] for a in library['artists'] for v in a['videos']))
    cached = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {'videos': {}}
    videos = cached['videos']
    pending = [video_id for video_id in ids if not videos.get(video_id, {}).get('date')]
    def save():
        temporary = OUTPUT.with_suffix('.tmp')
        temporary.write_text(json.dumps({'videos': videos}, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(OUTPUT)
    save()
    print(f'Cached {len(ids)-len(pending)}/{len(ids)}; fetching {len(pending)}', flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(fetch_date, video_id): video_id for video_id in pending}
        for count, task in enumerate(as_completed(tasks), 1):
            try:
                videos[tasks[task]] = task.result()
            except YouTubeRateLimited:
                for pending_task in tasks:
                    pending_task.cancel()
                save()
                raise
            save()
            if count % 25 == 0 or count == len(pending):
                print(f'Processed {count}/{len(pending)}; dates {sum(bool(videos.get(i,{}).get("date")) for i in ids)}/{len(ids)}', flush=True)
    return sum(bool(videos.get(i, {}).get('date')) for i in ids), len(ids)


if __name__ == '__main__':
    refresh()
