"""Single-channel Apple interpolation -> overlays -> HEVC, with bounded pipes.

Only a small scene map and lossless audio are staged on the internal disk.
Neither source-rate video, 60fps video nor frame images are written to disk.
The producer, interpolator and encoder have pipe backpressure and are reaped
together on failure; a partial video cannot become a delivered product.
"""
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from workflow import dual_render as render
from workflow.live.paths import ROOT
from workflow.original_master import video_recipe


def valid_audio(path, duration, probe):
    if not path.is_file():
        return False
    try:
        info = probe(path)
        if not any(s.get('codec_type') == 'audio' for s in info.get('streams', [])):
            return False
        return abs(float(info.get('format', {}).get('duration', 0))-duration) < .04
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def recover_audio(policy, source, audio, output, probe, ff):
    """AudioToolbox can return success with zero samples after an E-AC-3 seek.

    Keep the same decoder and source: decode from the beginning, reconstruct
    missing source timestamp intervals, then trim on the output clock. MPEG-TS
    gaps otherwise disappear in FLAC and shorten/shift the decoded audio.
    Validate before spending time interpolating any video.
    """
    start, end = policy['slice']
    duration = end-start
    if valid_audio(audio, duration, probe):
        return 'fast_seek'
    decoder = ['-c:a', policy['audio_decoder']] if policy.get('audio_decoder') else []
    command = [*ff, *decoder, '-i', str(source), '-ss', str(start), '-t', str(duration),
               '-map', '0:a:0', '-vn', '-af', 'aresample=async=1:first_pts=0', '-c:a', 'flac', '-ar', '48000',
               '-sample_fmt', 's32', '-bits_per_raw_sample', '24', str(audio)]
    with (output/'audio-recovery.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=log)
    if not valid_audio(audio, duration, probe):
        raise RuntimeError('原片音频解码无有效音轨或时长不符；从头解码恢复亦失败，停止插帧')
    return 'decode_from_start'


def scene_cuts(raw, *, ts=False):
    """Use exactly the original-master scene detector on normalized gray frames."""
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64)
    if not len(frames):
        raise ValueError('原片没有可解码的视频帧')
    if ts:
        # Keep the older TS 50->60 path's flash/rebound thresholds too.
        values = frames.astype(np.float32)
        diff = np.abs(np.diff(values, axis=0)).mean(axis=(1, 2))
        cuts = []
        for i in np.where(diff > 22)[0]:
            rebound = np.abs(values[min(i+2, len(values)-1)]-values[i]).mean()
            if rebound < diff[i]*.5 or (i > 0 and diff[i] < diff[i-1]*.75):
                continue
            cuts.append(int(i+1))
        return len(frames), cuts
    cuts = []
    previous = frames[0].astype(float)
    for i in range(1, len(frames)):
        current = frames[i].astype(float)
        difference = np.abs(current - previous).mean()
        if difference > 22 and (i+1 == len(frames) or np.abs(frames[i+1] - previous).mean() >= difference * .5):
            cuts.append(i)
        previous = current
    return len(frames), cuts


def reap(processes):
    """Stop every stage after an error, including a blocked pipe producer."""
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for handle in (process.stdin, process.stdout):
            if handle is not None and not handle.closed:
                handle.close()


def wait_pipeline(processes):
    # Poll all stages: waiting only for the encoder can deadlock when one of
    # its looped image inputs keeps it alive after an upstream failure.
    try:
        while True:
            codes = [process.poll() for process in processes]
            if any(code is not None and code != 0 for code in codes):
                raise RuntimeError(f'流式制作进程失败：{codes}')
            if all(code == 0 for code in codes):
                return
            time.sleep(.1)
    finally:
        reap(processes)


def encode(policy, source, output, cache, platform, probe, ff, status):
    from workflow.content_check import require_job
    require_job(policy, output, source)
    if cache.stat().st_dev != Path('/System/Volumes/Data').stat().st_dev:
        raise RuntimeError('流式插帧暂存必须在本机内置盘')
    video = next(s for s in probe(source)['streams'] if s['codec_type'] == 'video')
    rate, width, height, filters = video_recipe(video, policy.get('input_color_matrix'))
    start, end = policy['slice']
    duration = end-start
    source_input = ['-ss', str(start)]
    if policy.get('audio_decoder'):
        source_input += ['-c:a', policy['audio_decoder']]
    source_input += ['-i', str(source)]
    audio = cache / 'audio.flac'
    t = time.monotonic()
    needs_interpolation = rate != Fraction(60)
    status('流式准备：音频和切镜索引（不写入中间视频）')
    audio_args = ['-map', '0:a:0', '-t', str(duration), '-c:a', 'flac',
                  '-ar', '48000', '-sample_fmt', 's32', '-bits_per_raw_sample', '24', str(audio)]
    command = [*ff, *source_input, *audio_args]
    if needs_interpolation:
        command += ['-map', '0:v:0', '-an', '-t', str(duration), '-vf',
                    ','.join([*filters, 'scale=64:36', 'format=gray']),
                    '-r', str(rate), '-fps_mode', 'cfr', '-f', 'rawvideo', 'pipe:1']
    with (output / 'stream-prepare.log').open('w') as log:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=log)
    audio_seek_mode = recover_audio(policy, source, audio, output, probe, ff)
    render.save(output/'audio-source.json', {'decoder': policy.get('audio_decoder', 'default'),
                                           'seek_mode': audio_seek_mode, 'slice': policy['slice']})
    count, cuts = (scene_cuts(result.stdout, ts=policy.get('kind') == 'ts' and policy.get('fps') == 50)
                   if needs_interpolation else (round(duration*60), []))
    cut_file = cache / 'cuts.json'
    cut_file.write_text(json.dumps(cuts))
    render.timing('stream_audio_scene_prepare', time.monotonic()-t,
                  source_frames=count, source_rate=str(rate), width=width, height=height,
                  audio_seek_mode=audio_seek_mode)
    binary = cache / 'interpolate'
    if needs_interpolation:
        subprocess.run(['clang', '-O2', '-fobjc-arc', '-framework', 'Foundation',
                        '-framework', 'VideoToolbox', '-framework', 'CoreMedia', '-framework', 'CoreVideo',
                        str(ROOT / 'workflow/native/apple_interpolate.m'), '-o', str(binary)], check=True)
    kind = {'bilibili': 'landscape', 'douyin': 'portrait'}[platform]
    name = 'bilibili-4k60' if platform == 'bilibili' else 'douyin-1080p60'
    pending = output / (name + '.pending.mp4')
    inputs = ['-f', 'rawvideo', '-pixel_format', 'nv12', '-video_size', f'{width}x{height}',
              '-framerate', '60', '-i', 'pipe:0',
              '-loop', '1', '-framerate', '60', '-i', str(output/'header.png'),
              '-loop', '1', '-framerate', '60', '-i', str(output/f'{kind}-mask.png'),
              '-loop', '1', '-framerate', '60', '-i', str(ROOT/'assets/adele-logo.png'),
              '-i', str(audio)]
    decode = [*ff, '-progress', str(output/'stream-decode.progress'), *source_input,
              '-t', str(duration), '-map', '0:v:0', '-an', '-vf', ','.join(filters),
              '-r', str(rate), '-fps_mode', 'cfr', '-pix_fmt', 'nv12', '-f', 'rawvideo', 'pipe:1']
    status('单渠道流式：苹果插帧 → 字幕/水印 → 苹果HEVC编码')
    processes = []
    t = time.monotonic()
    try:
        with (output/'stream.log').open('w') as log:
            decoder = subprocess.Popen(decode, stdout=subprocess.PIPE, stderr=log)
            processes.append(decoder)
            frames = decoder.stdout
            if needs_interpolation:
                interpolator = subprocess.Popen([str(binary), str(count), str(round(duration*60)), str(cut_file),
                        str(rate.numerator), str(rate.denominator), str(width), str(height)],
                        stdin=frames, stdout=subprocess.PIPE, stderr=log)
                frames.close()
                processes.append(interpolator)
                frames = interpolator.stdout
            encoder = subprocess.Popen(render.encode_command(kind, inputs, '4:a:0', pending, duration),
                                       stdin=frames, stdout=log, stderr=log)
            frames.close()
            processes.append(encoder)
            wait_pipeline(processes)
    except BaseException:
        reap(processes)
        pending.unlink(missing_ok=True)
        raise
    seconds = time.monotonic()-t
    # This stage is fused: interpolation and encoding overlap. Do not add its
    # time to a second, fictional interpolation duration in reports.
    render.timing(name+'_render_encode', seconds, output=str(output/(name+'.mp4')),
                  duration=duration, pipeline='stream', includes_interpolation=needs_interpolation)
    return [(platform, pending)]
