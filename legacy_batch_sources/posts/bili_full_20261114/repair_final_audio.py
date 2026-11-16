"""Recover source FLAC audio for the two early AAC products, preserving video."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path('/Users/gold/repos/adele')
sys.path.insert(0, str(ROOT))
from workflow.live.paths import read_json, write_json
from post_bili.receipt import current_receipt
from post_bili.upload import check_spec

OUT = ROOT / 'posts/bili_full_20261114/final-seven-repair'


def run(args):
    return subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error', *args], stderr=subprocess.PIPE)


def repair(name):
    directory = ROOT / 'posts/grammys_2014' / name
    if current_receipt(directory):
        raise ValueError('稿件已提交，不改变成品')
    video = Path(read_json(directory / 'post/bili_upload.json')['视频文件'])
    manifest = read_json(video.parent / 'products.json')
    item = next(i for i in manifest['items'] if i['platform'] == 'bilibili')
    if not check_spec(video)[1]:
        print(name, 'already FLAC', flush=True)
        return
    master = video.parent / 'master60.mkv'
    backup = video.with_name('bilibili-4k60.before-flac.mp4')
    if backup.exists():
        raise ValueError('存在音轨修复备份，需先核对')
    temp = video.with_name('bilibili-4k60.flac-pending.mp4')
    duration = item['duration']
    audio_filter = f'apad=whole_dur={duration},atrim=duration={duration},asetpts=PTS-STARTPTS'
    print(name, '从共享母版恢复 FLAC，起点', item['start'], '时长', duration, flush=True)
    run(['-y', '-i', str(video), '-ss', str(item['start']), '-i', str(master),
         '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-tag:v', 'hvc1',
         '-c:a', 'flac', '-sample_fmt', 's32', '-bits_per_raw_sample', '24',
         '-ar', '48000', '-af', audio_filter,
         '-strict', '-2', '-t', str(duration), '-movflags', '+faststart', str(temp)])
    assert not check_spec(temp)[1], check_spec(temp)
    old_video_hash = run(['-i', str(video), '-map', '0:v:0', '-c:v', 'copy', '-f', 'hash', '-hash', 'sha256', '-']).decode().strip()
    new_video_hash = run(['-i', str(temp), '-map', '0:v:0', '-c:v', 'copy', '-f', 'hash', '-hash', 'sha256', '-']).decode().strip()
    assert old_video_hash == new_video_hash, '视频码流不一致'
    expected_audio = run(['-ss', str(item['start']), '-i', str(master), '-map', '0:a:0',
                          '-af', audio_filter, '-ar', '48000', '-c:a', 'pcm_s24le',
                          '-f', 'hash', '-hash', 'sha256', '-']).decode().strip()
    actual_audio = run(['-i', str(temp), '-map', '0:a:0', '-c:a', 'pcm_s24le',
                        '-f', 'hash', '-hash', 'sha256', '-']).decode().strip()
    assert expected_audio == actual_audio, '音频采样与母版截取不一致'
    if current_receipt(directory):
        raise ValueError('核验期间已投稿，保留候选文件待核对')
    write_json(OUT / (name + '-products-before-flac.json'), manifest)
    video.rename(backup)
    temp.rename(video)
    item.update(audio_codec='flac', sample_rate=48000, audio_bits=24)
    if item.get('sha256'):
        with video.open('rb') as f:
            item['sha256'] = hashlib.file_digest(f, 'sha256').hexdigest()
    manifest.setdefault('audio_repairs', []).append({
        'platform': 'bilibili', 'source': str(master), 'start': item['start'],
        'duration': duration, 'backup': str(backup),
        'video_sha256_unchanged': new_video_hash, 'decoded_audio_sha256': actual_audio,
        'verification': '视频码流逐字节一致；24bit PCM 与共享母版对应时间段逐采样一致'})
    write_json(video.parent / 'products.json', manifest)
    write_json(OUT / (name + '-flac-verified.json'), manifest['audio_repairs'][-1])
    print(name, 'FLAC修复完成，视频码流与音频采样均已核验', flush=True)


for song in ['02_royals', '04_dark_horse']:
    try:
        repair(song)
    except Exception as error:
        from post_bili.edit_description import redacted_error
        print(song, '待处理', redacted_error(error), flush=True)
