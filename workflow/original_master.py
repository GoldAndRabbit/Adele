"""Prepare a song-local 60fps SDR master from the confirmed original source."""
from fractions import Fraction
import json
import shutil
import subprocess as sp
from pathlib import Path

import numpy as np

from workflow.live.paths import ROOT


def video_recipe(video, input_color_matrix=None):
    """Shared normalization for cached and direct-stream delivery paths."""
    rate = Fraction(video["r_frame_rate"])
    filters = []
    if video.get("field_order") not in (None, "progressive", "unknown"):
        filters.append("bwdif=mode=send_field:parity=auto:deint=all")
        rate *= 2
    if video.get("color_transfer") in ("arib-std-b67", "smpte2084"):
        linear = "zscale=t=linear:npl=100"
        # Match the confirmed browser preview's handling of HLG broadcasts
        # tagged bt2020c, which zscale cannot convert directly.
        input_color_matrix = input_color_matrix or ('bt2020nc' if video.get('color_space') == 'bt2020c' else None)
        if input_color_matrix:
            if input_color_matrix != "bt2020nc":
                raise ValueError(f"不支持的输入色彩矩阵覆盖 {input_color_matrix}")
            linear = "zscale=matrixin=bt2020nc:t=linear:npl=100"
        filters.extend([linear, "format=gbrpf32le", "zscale=p=bt709",
                        "tonemap=mobius", "zscale=t=bt709:m=bt709:r=limited"])
    width, height = video["width"], video["height"]
    # Normalise non-widescreen footage without stretching the source into the layout.
    if width * 9 != height * 16 or video.get("sample_aspect_ratio") not in (None, "N/A", "1:1"):
        target = 3840 if width > 1920 else 1920
        filters.extend(["scale=trunc(iw*sar/2)*2:ih,setsar=1",
                        f"scale={target}:{target*9//16}:force_original_aspect_ratio=decrease",
                        f"pad={target}:{target*9//16}:(ow-iw)/2:(oh-ih)/2"])
        width, height = target, target * 9 // 16
    filters.extend(["setsar=1", "format=yuv420p"])
    return rate, width, height, filters


def prepare(source, start, duration, directory, probe, ff, *, log_dir=None, input_color_matrix=None, audio_decoder=None):
    def progress(stage):
        return ["-progress", str(log_dir / (stage + ".progress"))] if log_dir else []

    video = next(s for s in probe(source)["streams"] if s["codec_type"] == "video")
    rate, width, height, filters = video_recipe(video, input_color_matrix)
    native = directory / "native.mkv"
    sp.run(ff + progress("native") + ["-ss", str(start), *(["-c:a", audio_decoder] if audio_decoder else []), "-i", str(source), "-t", str(duration),
                 "-map", "0:v:0", "-map", "0:a:0", "-vf", ",".join(filters), "-r", str(rate),
                 "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
                 "-c:a", "flac", str(native)], check=True)
    master = directory / "master60.mkv"
    if rate == 60:
        master.hardlink_to(native)
        return native
    required = int(native.stat().st_size * 60 / float(rate)) + 2 * 1024**3
    if shutil.disk_usage(directory).free < required:
        raise RuntimeError(f"内置盘剩余空间不足，生成共享母版预计还需 {required / 1024**3:.1f} GiB")
    thumb = sp.check_output(ff + ["-i", str(native), "-an", "-vf", "scale=64:36,format=gray",
                                  "-f", "rawvideo", "-"])
    frames = np.frombuffer(thumb, np.uint8).reshape(-1, 36, 64)
    cuts = []
    previous = frames[0].astype(float)
    for i in range(1, len(frames)):
        current = frames[i].astype(float)
        difference = np.abs(current - previous).mean()
        if difference > 22 and (i+1 == len(frames) or np.abs(frames[i+1] - previous).mean() >= difference * .5):
            cuts.append(i)
        previous = current
    cut_file = directory / "cuts.json"
    cut_file.write_text(json.dumps(cuts))
    binary = directory / "interpolate"
    sp.run(["clang", "-O2", "-fobjc-arc", "-framework", "Foundation", "-framework", "VideoToolbox",
            "-framework", "CoreMedia", "-framework", "CoreVideo", str(ROOT/"workflow/native/apple_interpolate.m"),
            "-o", str(binary)], check=True)
    with sp.Popen(ff + ["-i", str(native), "-an", "-pix_fmt", "nv12", "-f", "rawvideo", "-"], stdout=sp.PIPE) as dec:
        with sp.Popen([binary, str(len(frames)), str(round(duration*60)), cut_file, str(rate.numerator),
                       str(rate.denominator), str(width), str(height)], stdin=dec.stdout, stdout=sp.PIPE) as inter:
            dec.stdout.close()
            with sp.Popen(ff + progress("master") + ["-f", "rawvideo", "-pixel_format", "nv12", "-video_size", f"{width}x{height}",
                                "-framerate", "60", "-i", "-", "-i", str(native), "-map", "0:v:0", "-map", "1:a:0",
                                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-c:a", "copy",
                                str(master)], stdin=inter.stdout) as enc:
                inter.stdout.close()
                if enc.wait() or inter.wait() or dec.wait():
                    raise RuntimeError("共享母版插帧失败")
    return native
