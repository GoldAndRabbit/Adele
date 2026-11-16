"""On-demand local previews; never open media while listing downloads."""
import hashlib
from fractions import Fraction
import json
from pathlib import Path
import re
import subprocess
from threading import Lock, Semaphore, Thread

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/selection-downloads')
_lock = Lock()
_slots = Semaphore(1)
_jobs = {}


def storage():
    root = Path(json.loads((ROOT / 'external_storage.json').read_text())['root'])
    if not (Path('/Volumes') / root.parts[2]).is_mount():
        raise HTTPException(503, '移动硬盘尚未挂载')
    return root / 'selection-downloads'


def queue():
    path = storage() / '_queue/queue.json'
    if not path.is_file():
        return {'items': []}
    return json.loads(path.read_text())


def downloaded(video_id):
    if not re.fullmatch(r'[\w-]{11}', video_id, re.ASCII):
        raise HTTPException(404, '没有这个视频')
    root = storage().resolve()
    item = next((i for i in queue()['items'] if i['video_id'] == video_id and i['status'] == 'completed'), None)
    if not item or not item.get('path'):
        raise HTTPException(404, '视频尚未下载完成')
    source = Path(item['path']).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise HTTPException(404, '原视频不存在或不在下载目录')
    return item, source


def target_for(source, video_id):
    source = source.resolve()
    stat = source.stat()
    key = hashlib.sha256(f'{source}:{stat.st_size}:{stat.st_mtime_ns}:720p-v1'.encode()).hexdigest()[:20]
    return storage() / '_previews' / f'{video_id}-{key}.mp4'


def preview_state(item, target):
    if target.is_file():
        return {'status': 'ready', 'title': item['title'], 'artist': item['artist'],
                'media_url': f"/api/selection-downloads/{item['video_id']}/media"}
    return {'status': _jobs.get(str(target), 'not_started'), 'title': item['title'], 'artist': item['artist']}


def source_specs(item):
    video = next((stream for stream in (item.get('media') or {}).get('streams', [])
                  if stream.get('codec_type') == 'video'), {})
    fps = None
    for key in ('avg_frame_rate', 'r_frame_rate'):
        try:
            rate = float(Fraction(str(video.get(key, '0'))))
            if rate > 0:
                fps = round(rate, 2)
                break
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
    width, height = video.get('width'), video.get('height')
    resolution = None
    if width and height:
        short = min(width, height)
        resolution = f'{short}p' + ('（4K）' if short == 2160 else '（8K）' if short == 4320 else '')
    return {'fps': fps, 'resolution': resolution}


@router.get('')
def downloads():
    # JSON/status only: no video reads, thumbnail extraction or preview generation.
    return {'videos': {i['video_id']: {'status': i['status'], **source_specs(i),
                       'preview_url': f"/selection-preview.html?id={i['video_id']}" if i['status'] == 'completed' else None}
                       for i in queue()['items']}}


def build(source, target):
    partial = target.with_suffix('.partial.mp4')
    try:
        with _slots:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.with_suffix('.log').open('a') as log:
                # All generated media, including partial files, stays on the external disk.
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-threads', '2',
                                '-i', str(source), '-map', '0:v:0', '-map', '0:a:0',
                                '-vf', 'scale=w=min(1280\\,iw):h=min(720\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2',
                                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-threads', '2',
                                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                                '-movflags', '+faststart', str(partial)], stdout=log, stderr=log,
                               check=True, timeout=1800)
            partial.replace(target)
        with _lock:
            _jobs.pop(str(target), None)
    except (OSError, subprocess.SubprocessError):
        partial.unlink(missing_ok=True)
        with _lock:
            _jobs[str(target)] = 'failed'


def original_state(item):
    return {'status': 'ready', 'mode': 'original', 'title': item['title'], 'artist': item['artist'],
            'media_url': f"/api/selection-downloads/{item['video_id']}/original"}


@router.get('/{video_id}/original')
def original_media(video_id: str):
    _, source = downloaded(video_id)
    mime = {'.mp4': 'video/mp4', '.webm': 'video/webm', '.mkv': 'video/x-matroska'}.get(source.suffix.lower(), 'application/octet-stream')
    return FileResponse(source, media_type=mime, headers={'Cache-Control': 'no-cache'})


@router.post('/{video_id}/preview')
def prepare(video_id: str, compatible: bool = False):
    item, source = downloaded(video_id)
    if not compatible:
        return original_state(item)
    target = target_for(source, video_id)
    with _lock:
        if not target.is_file() and _jobs.get(str(target)) != 'building':
            _jobs[str(target)] = 'building'
            Thread(target=build, args=(source, target), daemon=True).start()
        return preview_state(item, target)


@router.get('/{video_id}/preview')
def status(video_id: str, compatible: bool = False):
    item, source = downloaded(video_id)
    if not compatible:
        return original_state(item)
    with _lock:
        return preview_state(item, target_for(source, video_id))


@router.get('/{video_id}/media')
def media(video_id: str):
    _, source = downloaded(video_id)
    target = target_for(source, video_id)
    if not target.is_file():
        raise HTTPException(404, '请先打开预览页准备视频')
    return FileResponse(target, media_type='video/mp4', headers={'Cache-Control': 'no-cache'})
