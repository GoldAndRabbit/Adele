#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
歌曲链接 -> 4K + 60帧插帧 + 水印 + 双语歌词 视频，bzrp.sh 流程的自动化版本。

阶段（可用 --from / --to 断点续跑）:
  download   yt-dlp 下载原视频 + 官方字幕         -> work/<name>/source.mp4
  prep       截取片段、降到 1080p、导出 flac       -> work/<name>/video_1080.mp4, audios/<name>.flac
  lyrics     官方字幕优先，否则 demucs + whisper   -> ori_lyrics/<name>.srt   (需人工校对)
  split      过长的句子在停顿处拆开，切点对齐人声   -> ori_lyrics/<name>.srt（原地）
  translate  调 API 生成双语 ass                  -> lyrics/<name>.ass        (需人工校对)
  interp     原生帧率抽帧 + RIFE 直接插到 60fps     -> work/<name>/frames_out/
  render     放大到 4K + 烧字幕 + 水印             -> post/<name> 4K60FPS Sub-WaterMark.mp4

用法:
  my_venv/bin/python pipeline/make_mv.py --name bzrp --url "https://..." --lang Spanish --to lyrics
  # 校对 ori_lyrics/bzrp.srt 后
  my_venv/bin/python pipeline/make_mv.py --name bzrp --from translate --title "《...》 Artist"
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = ROOT / "my_venv" / "bin"
STAGES = ["download", "prep", "lyrics", "split", "translate", "interp", "render"]
TARGET_FPS = 60


def run(cmd, cwd=None):
    print("\n$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd)


def tool(name):
    """优先使用 my_venv 里的命令（yt-dlp / whisper / demucs）。"""
    p = VENV_BIN / name
    return str(p) if p.exists() else name


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,width,height:format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    num, den = d["streams"][0]["r_frame_rate"].split("/")
    return {
        "fps": float(num) / float(den),
        "fps_str": d["streams"][0]["r_frame_rate"],
        "width": d["streams"][0]["width"],
        "height": d["streams"][0]["height"],
        "duration": float(d["format"]["duration"]),
    }


def to_seconds(t):
    if t is None:
        return None
    parts = [float(x) for x in str(t).split(":")]
    s = 0.0
    for x in parts:
        s = s * 60 + x
    return s


# ---------------------------------------------------------------- stages

def stage_download(a, w):
    src = w / "source.mp4"
    if src.exists():
        print(f"已存在 {src}，跳过下载")
        return
    cmd = [tool("yt-dlp"), "--no-playlist",
           "-f", "bestvideo[height<=2160]+bestaudio/best",
           "--merge-output-format", "mp4",
           "--write-subs", "--sub-langs", "all,-live_chat", "--convert-subs", "srt",
           "-o", str(w / "source.%(ext)s")]
    if a.cookies_from_browser:
        cmd += ["--cookies-from-browser", a.cookies_from_browser]
    if a.cookies:
        cmd += ["--cookies", a.cookies]
    run(cmd + [a.url])
    # 保存元信息，后面标题行会用到
    info = subprocess.run([tool("yt-dlp"), "--no-playlist", "--skip-download", "-J", a.url]
                          + (["--cookies-from-browser", a.cookies_from_browser] if a.cookies_from_browser else [])
                          + (["--cookies", a.cookies] if a.cookies else []),
                          capture_output=True, text=True)
    if info.returncode == 0:
        d = json.loads(info.stdout)
        keep = {k: d.get(k) for k in ("title", "channel", "duration", "language", "track", "artist")}
        (w / "meta.json").write_text(json.dumps(keep, ensure_ascii=False, indent=2))


def stage_prep(a, w):
    src = w / "source.mp4"
    info = probe(src)
    print(f"源视频: {info['width']}x{info['height']} @ {info['fps_str']} fps, {info['duration']:.1f}s")
    trim = []
    if a.start:
        trim += ["-ss", a.start]
    if a.end:
        trim += ["-to", a.end]

    # 统一降到 1080p 再插帧（4K 直接插帧太慢、太占盘）；帧率保持原生，后面交给 RIFE
    run(["ffmpeg", "-y", "-hide_banner", *trim, "-i", src,
         "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
         "-an", "-c:v", "libx264", "-crf", "12", "-preset", "fast", "-pix_fmt", "yuv420p",
         w / "video_1080.mp4"])

    # 高质量音频
    (ROOT / "audios").mkdir(exist_ok=True)
    run(["ffmpeg", "-y", "-hide_banner", *trim, "-i", src,
         "-vn", "-c:a", "flac", "-ar", "48000", "-sample_fmt", "s32",
         ROOT / "audios" / f"{a.name}.flac"])


def find_official_subs(a, w):
    """yt-dlp 下载的人工字幕，按 --sub-lang 选择（例如 es / en / ja）。"""
    subs = sorted(w.glob("source.*.srt"))
    if a.sub_lang:
        subs = [s for s in subs if s.name.split(".")[1].split("-")[0] == a.sub_lang]
    return subs[0] if subs else None


def stage_lyrics(a, w):
    import pysubs2

    out = ROOT / "ori_lyrics" / f"{a.name}.srt"
    if out.exists() and not a.force:
        print(f"已存在 {out}（人工校对过的不会被覆盖，--force 可重新生成）")
        return

    sub = find_official_subs(a, w) if not a.whisper else None
    if sub:
        print(f"使用官方字幕 {sub.name}")
        subs = pysubs2.load(str(sub))
        if a.start:  # 截取后时间轴需要平移
            subs.shift(s=-to_seconds(a.start))
            subs.events = [e for e in subs.events if e.end > 0]
            for e in subs.events:
                e.start = max(e.start, 0)
    else:
        flac = ROOT / "audios" / f"{a.name}.flac"
        # 人声分离后再识别，背景乐对 whisper 干扰很大
        run([tool("demucs"), flac, "-n", "htdemucs", "--two-stems=vocals",
             "-o", ROOT / "separated", "--jobs=4"])
        vocals = ROOT / "separated" / "htdemucs" / a.name / "vocals.wav"
        cmd = [tool("whisper"), vocals, "--model", a.whisper_model,
               "--temperature", "0.0", "--best_of", "5", "--beam_size", "5",
               "--condition_on_previous_text", "False",
               "--output_format", "srt", "--output_dir", w / "whisper",
               "--word_timestamps", "True", "--max_line_width", "48", "--max_line_count", "1"]
        if a.lang:
            cmd += ["--language", a.lang]
        run(cmd)
        subs = pysubs2.load(str(w / "whisper" / "vocals.srt"))

    out.parent.mkdir(exist_ok=True)
    subs.save(str(out))
    print(f"\n>>> 原文歌词已生成: {out}\n>>> 请对照正确歌词校对（时间轴不变，只改文字），然后用 --from translate 继续")


def stage_split(a, w):
    srt = ROOT / "ori_lyrics" / f"{a.name}.srt"
    vocals = ROOT / "separated" / "htdemucs" / a.name / "vocals.wav"
    if not vocals.exists():
        run([tool("demucs"), ROOT / "audios" / f"{a.name}.flac", "-n", "htdemucs",
             "--two-stems=vocals", "-o", ROOT / "separated", "--jobs=4"])
    backup = w / "ori_unsplit.srt"
    if not backup.exists():
        shutil.copy(srt, backup)
    run([sys.executable, ROOT / "pipeline" / "split_long.py", srt,
         "--vocals", vocals, "--max-width", a.max_width])


def stage_translate(a, w):
    src = ROOT / "ori_lyrics" / f"{a.name}.srt"
    out = ROOT / "lyrics" / f"{a.name}.ass"
    if out.exists() and not a.force:
        print(f"已存在 {out}（人工校对过的不会被覆盖，--force 可重新生成）")
        return
    title = a.title
    if not title and (w / "meta.json").exists():
        title = json.loads((w / "meta.json").read_text()).get("title")
    cmd = [sys.executable, ROOT / "pipeline" / "translate_ass.py", src, "-o", out]
    if title:
        cmd += ["--title", title]
    if a.zh_file:
        cmd += ["--zh-file", a.zh_file]
    run(cmd)
    print(f"\n>>> 双语字幕已生成: {out}，建议过一遍再 --from interp")


def pick_frame_ext(a, video, info, w):
    """估算 PNG 帧占用磁盘，放不下就改用高质量 JPEG（源本身就是 4:2:0，肉眼无损）。"""
    if a.frame_format != "auto":
        return a.frame_format
    sample = w / "_sample"
    shutil.rmtree(sample, ignore_errors=True)
    sample.mkdir()
    step = info["duration"] / 6
    for i in range(1, 6):
        run(["ffmpeg", "-v", "error", "-ss", f"{step * i:.2f}", "-i", video,
             "-frames:v", "1", sample / f"{i}.png"])
    avg = sum(f.stat().st_size for f in sample.glob("*.png")) / 5
    shutil.rmtree(sample)
    need = avg * info["duration"] * (info["fps"] + TARGET_FPS) * 1.3
    free = shutil.disk_usage(w).free
    print(f"PNG 预计占用 {need / 1e9:.0f}GB，剩余 {free / 1e9:.0f}GB")
    return "png" if need < free * 0.85 else "jpg"


def stage_interp(a, w):
    video = w / "video_1080.mp4"
    info = probe(video)
    fin, fout = w / "frames_in", w / "frames_out"
    for d in (fin, fout):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
    ext = pick_frame_ext(a, video, info, w)
    q = ["-q:v", "1"] if ext == "jpg" else []

    # 以原生帧率 CFR 抽帧（不像旧流程先 dup 到 30fps，避免 24/25fps 素材插帧后顿挫）
    run(["ffmpeg", "-hide_banner", "-i", video, "-vf", f"fps={info['fps_str']}", *q,
         fin / f"%08d.{ext}"])
    n_in = len(list(fin.glob(f"*.{ext}")))
    n_out = round(n_in * TARGET_FPS / info["fps"])

    if info["fps"] >= TARGET_FPS - 0.5:
        print("源已经是 60fps，跳过插帧")
        shutil.rmtree(fout)
        fin.rename(fout)
        return

    # RIFE v4 支持任意时间步，-n 直接指定目标帧数，一步到 60fps
    print(f"RIFE: {n_in} 帧 @ {info['fps']:.3f} -> {n_out} 帧 @ {TARGET_FPS} ({ext})")
    run([ROOT / "rife-ncnn-vulkan", "-i", fin, "-o", fout,
         "-m", ROOT / "models" / "rife-v4.6", "-n", n_out, "-j", "3:6:3", "-f", f"%08d.{ext}"])
    if not a.keep_frames:
        shutil.rmtree(fin)


def stage_render(a, w):
    ass = Path(a.ass).resolve() if a.ass else ROOT / "lyrics" / f"{a.name}.ass"
    if not ass.exists():
        sys.exit(f"缺少字幕 {ass}")
    # ass 滤镜对路径里的空格/冒号转义很麻烦，拷到工作目录用相对路径
    shutil.copy(ass, w / "subs.ass")
    post = ROOT / "post"
    post.mkdir(exist_ok=True)
    tag = f" {a.tag}" if a.tag else ""
    out = post / f"{a.name} 4K60FPS Sub-WaterMark{tag}.mp4"
    ext = "jpg" if any((w / "frames_out").glob("*.jpg")) else "png"

    if a.fast:
        venc = ["-c:v", "hevc_videotoolbox", "-q:v", "70", "-tag:v", "hvc1"]
    else:
        venc = ["-c:v", "libx264", "-crf", str(a.crf), "-preset", "medium",
                "-profile:v", "high", "-level", "5.2"]

    run(["ffmpeg", "-y", "-hide_banner",
         "-framerate", TARGET_FPS, "-i", f"frames_out/%08d.{ext}",
         "-i", ROOT / "audios" / f"{a.name}.flac",
         "-i", ROOT / a.logo,
         "-filter_complex",
         "[0:v]scale=3840:2160:flags=lanczos,ass=subs.ass[sub];"
         f"[2:v]scale=iw*{a.logo_scale}:-1[wm];"
         "[sub][wm]overlay=15:15:format=auto,format=yuv420p[v]",
         "-map", "[v]", "-map", "1:a",
         *venc,
         "-c:a", "aac", "-b:a", "320k",
         "-shortest", "-movflags", "+faststart",
         out], cwd=w)
    print(f"\n>>> 成品: {out}")
    if not a.keep_frames:
        shutil.rmtree(w / "frames_out", ignore_errors=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="歌曲短名，用于所有文件名，如 bzrp")
    p.add_argument("--url", help="YouTube 链接（download 阶段需要）")
    p.add_argument("--start", help="截取开始时间，如 00:36:37")
    p.add_argument("--end", help="截取结束时间，如 00:40:04")
    p.add_argument("--lang", help="whisper 语言，如 English / Spanish / Japanese；不填自动识别")
    p.add_argument("--sub-lang", help="优先使用的官方字幕语言代码，如 en / es / ja")
    p.add_argument("--whisper", action="store_true", help="忽略官方字幕，强制 whisper 识别")
    p.add_argument("--whisper-model", default="large-v3")
    p.add_argument("--max-width", type=int, default=40,
                   help="单句最大显示宽度（全角算 2），超过就拆")
    p.add_argument("--title", help="字幕首行标题，如 '《Song》 Artist'")
    p.add_argument("--zh-file", help="不调 API，直接用这个文件里的中文翻译（每行对应一句）")
    p.add_argument("--cookies-from-browser", help="yt-dlp 需要登录时: chrome / safari / firefox")
    p.add_argument("--cookies", help="cookies.txt 路径")
    p.add_argument("--ass", help="render 用的字幕文件，默认 lyrics/<name>.ass")
    p.add_argument("--tag", help="成品文件名后缀，用于对比不同版本，如 bzrpv2style")
    p.add_argument("--logo", default="adele-logo.png")
    p.add_argument("--logo-scale", default="0.10")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--fast", action="store_true", help="用 VideoToolbox HEVC 硬编，快很多")
    p.add_argument("--frame-format", choices=["auto", "png", "jpg"], default="auto",
                   help="中间帧格式，auto 会按磁盘余量选择")
    p.add_argument("--keep-frames", action="store_true", help="保留 PNG 帧（默认渲染后删除，很占盘）")
    p.add_argument("--force", action="store_true", help="覆盖已存在的歌词/字幕文件")
    p.add_argument("--from", dest="from_", choices=STAGES, default=STAGES[0])
    p.add_argument("--to", choices=STAGES, default=STAGES[-1])
    a = p.parse_args()

    w = ROOT / "work" / a.name
    w.mkdir(parents=True, exist_ok=True)
    stages = STAGES[STAGES.index(a.from_): STAGES.index(a.to) + 1]
    if "download" in stages and not a.url:
        p.error("download 阶段需要 --url")
    for s in stages:
        print(f"\n========== [{s}] ==========", flush=True)
        globals()[f"stage_{s}"](a, w)


if __name__ == "__main__":
    main()
