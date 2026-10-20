#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
歌曲链接 -> 4K60 + 水印 + 原文/中文双语字幕 + FLAC Hi-Res 的成品视频。

阶段（可用 --from / --to 断点续跑）:
  download   yt-dlp 下载原视频 + 官方字幕 + 元信息      -> posts/<name>/source.mp4, meta.json
  prep       截取片段、降到 1080p、导出 FLAC 48k/24bit  -> posts/<name>/video_1080.mp4, audio.flac
  lyrics     参考歌词：官方带时间字幕优先（--sub-lang，只取文字），
             否则 get_ytb_lyrics_from_link.py 从 Genius 取歌词文本 -> posts/<name>/lyrics.txt
  separate   Mel-Band RoFormer 人声分离（.venv-sep）    -> posts/<name>/vocals.wav
  interp     原生帧率抽帧 + RIFE 一步插到 60fps          -> posts/<name>/frames_out/

字幕对齐、翻译、注释走 v4（.venv/bin/python -m workflow_v4.run post <name>），
4K 渲染（字幕 + logo + 水印 + FLAC）走 .venv/bin/python -m workflow_v4.render post:<name>（它调本脚本的 interp）。

用法:
  .venv/bin/python workflow/make_mv.py --name X --url "https://..." --to separate
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import BIN, MODELS, POSTS, ROOT, WORKFLOW as PIPE, Song  # noqa: E402

VENV_BIN = ROOT / ".venv" / "bin"
SEP_PY = ROOT / ".venv-sep" / "bin" / "python"
STAGES = ["download", "prep", "lyrics", "separate", "interp"]
TARGET_FPS = 60


def run(cmd, cwd=None):
    print("\n$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd)


def tool(name):
    """优先使用 .venv 里的命令（yt-dlp）。"""
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
    # 下载参数和 SubDub（../SubDub/subdub/pipeline.py stage_download）保持一致
    cmd = [tool("yt-dlp"), "--no-playlist",
           # 画质最高到 2160p（这里和 SubDub 不同，SubDub 只要 1080p）；很多视频带 YouTube 自动配音的多语种音轨，
           # bestaudio 可能选到德语 / 印地语，只要原声
           "-f", "bv*[height<=2160]+ba[format_note*=original]/bv*[height<=2160]+ba[language^=en]/bv*+ba/b",
           # 有的视频不给 PO token 只出 360p 合流：本机起了 bgutil PO token 服务时 mweb 客户端能拿到 1080p；
           # 没起服务也不影响 default 客户端（需要 yt-dlp-ejs + deno 解 JS 校验，见 requirements.txt）
           "--extractor-args", "youtube:player_client=default,mweb",
           "--merge-output-format", "mp4", "--retries", "10", "--fragment-retries", "10",
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
        keep = {k: d.get(k) for k in ("title", "channel", "duration", "language", "track", "artist",
                                    "upload_date", "description", "tags", "webpage_url")}
        (w / "meta.json").write_text(json.dumps(keep, ensure_ascii=False, indent=2))


def mid_size(src):
    """中间视频的画面大小：要插帧的降到 1080p（4K 直接插帧太慢、太占盘）；
    原片已经是 60 帧（不插帧）且高于 1080p 的，保留原分辨率（如 1440p），渲染时直接放大到 4K，不白白损失清晰度。"""
    info = probe(src)
    if info["fps"] >= TARGET_FPS - 0.5 and info["height"] > 1080:
        h = min(2160, info["height"]) // 2 * 2
        return round(h * 16 / 9) // 2 * 2, h
    return 1920, 1080


def make_1080(a, w):
    """中间视频 video_1080.mp4（文件名沿用；大小见 mid_size）；帧率保持原生，后面交给 RIFE。"""
    trim = (["-ss", a.start] if a.start else []) + (["-to", a.end] if a.end else [])
    tmp = w / "video_1080.partial.mp4"
    W, H = mid_size(w / "source.mp4")
    run(["ffmpeg", "-y", "-hide_banner", *trim, "-i", w / "source.mp4",
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1",
         "-an", "-c:v", "libx264", "-crf", "12", "-preset", "fast", "-pix_fmt", "yuv420p", tmp])
    tmp.replace(w / "video_1080.mp4")  # 写完整才改名：中途被停不会留下半截文件


def video_1080_ok(a, w):
    """中间视频存在、大小对（mid_size）、时长和源视频（截取后）一致。"""
    v = w / "video_1080.mp4"
    if not v.exists():
        return False
    src = probe(w / "source.mp4")["duration"]
    if a.start or a.end:
        src = (to_seconds(a.end) if a.end else src) - (to_seconds(a.start) or 0)
    info = probe(v)
    return abs(info["duration"] - src) < 1.0 and (info["width"], info["height"]) == mid_size(w / "source.mp4")


def stage_prep(a, w):
    src = w / "source.mp4"
    info = probe(src)
    print(f"源视频: {info['width']}x{info['height']} @ {info['fps_str']} fps, {info['duration']:.1f}s")
    trim = []
    if a.start:
        trim += ["-ss", a.start]
    if a.end:
        trim += ["-to", a.end]

    make_1080(a, w)

    # 高质量音频
    run(["ffmpeg", "-y", "-hide_banner", *trim, "-i", src,
         "-vn", "-c:a", "flac", "-ar", "48000", "-sample_fmt", "s32", Song(a.name).audio])


def find_official_subs(a, w):
    """yt-dlp 下载的人工字幕，按 --sub-lang 选择（例如 es / en / ja）；不指定 --sub-lang 就不用官方字幕。"""
    if not a.sub_lang:
        return None
    subs = [s for s in sorted(w.glob("source.*.srt")) if s.name.split(".")[1].split("-")[0] == a.sub_lang]
    return subs[0] if subs else None


def paths(a, w):
    S = Song(a.name)
    return {"srt": S.lyrics_srt, "txt": S.lyrics_txt, "vocals": S.vocals, "source": S.lyrics_source}


def stage_lyrics(a, w):
    """参考歌词。官方带时间字幕（人工打轴）优先；否则用 Genius 歌词文本。"""
    import pysubs2

    p = paths(a, w)
    sub = find_official_subs(a, w)
    if sub:
        print(f"使用官方字幕 {sub.name}")
        subs = pysubs2.load(str(sub))
        if a.start:  # 截取后时间轴需要平移
            subs.shift(s=-to_seconds(a.start))
            subs.events = [e for e in subs.events if e.end > 0]
            for e in subs.events:
                e.start = max(e.start, 0)
        shutil.copy(sub, Song(a.name).official_srt)
        subs.save(str(p["srt"]))
        p["txt"].write_text("\n".join(e.plaintext.replace("\n", " ").strip() for e in subs.events if e.plaintext.strip()) + "\n")   # v4 读歌词文本
        p["source"].write_text("official")
        return
    if not p["txt"].exists():
        cmd = [sys.executable, PIPE / "get_ytb_lyrics_from_link.py", a.url or "", "--name", a.name]
        if a.genius_url:
            cmd += ["--genius-url", a.genius_url]
        if a.song_title:
            cmd += ["--title", a.song_title]
        if a.artist:
            cmd += ["--artist", a.artist]
        if a.cookies:
            cmd += ["--cookies", a.cookies]
        run(cmd)
    secs = w / "lyrics_sections.txt"
    if not secs.exists() and (a.url or a.genius_url):
        # 再抓一份带 [段落] 标记的，align 用来按段落对齐（抓不到不影响主流程）
        tmp = f"_{a.name}_sections"
        cmd = [sys.executable, PIPE / "get_ytb_lyrics_from_link.py", a.url or "", "--name", tmp, "--keep-sections", "--overwrite"]
        for k, v in (("--genius-url", a.genius_url), ("--title", a.song_title), ("--artist", a.artist), ("--cookies", a.cookies)):
            if v:
                cmd += [k, v]
        if subprocess.run([str(c) for c in cmd]).returncode == 0:
            (POSTS / tmp / "lyrics.txt").replace(secs)
        shutil.rmtree(POSTS / tmp, ignore_errors=True)
    print(f"参考歌词: {p['txt']}（建议过一眼：现场版和录音室版的歌词可能不同）")
    p["source"].write_text("reference")


def stage_separate(a, w):
    p = paths(a, w)
    if p["vocals"].exists() and not a.force:
        print(f"已存在 {p['vocals']}")
        return
    if not SEP_PY.exists():
        sys.exit("缺少人声分离环境 .venv-sep（见 README 安装说明）")
    run([SEP_PY, PIPE / "separate_roformer.py", Song(a.name).audio, "-o", p["vocals"]])








TITLE_PROMPT = """从 YouTube 视频标题里提取演唱的歌名和歌手，输出 JSON {"title": "《歌名》 歌手"}。
- 只用标题和简介里明确写出的信息，不要猜；歌名、歌手保持原文写法
- 多首歌（串烧）用 " / " 分隔，按标题里的顺序：《歌1 / 歌2》 歌手
- 去掉节目名、日期、频道名、Official Video / Live / 4K / Lyrics 等标签；合作歌手用 " & " 连接"""


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
    if not video_1080_ok(a, w):  # 被清理掉了、或之前被中断只写了一半，都从源视频重建
        make_1080(a, w)
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
    run([BIN / "rife-ncnn-vulkan", "-i", fin, "-o", fout,
         "-m", MODELS / "rife-v4.6", "-n", n_out, "-j", "3:6:3", "-f", f"%08d.{ext}"])
    shutil.rmtree(fin)  # 插帧前的原始帧只在重新插帧时有用，随时能从源视频重抽；重新渲染只需要 frames_out


def check_hires(path):
    """成品音轨必须是 FLAC 48kHz/24bit，否则 B 站不显示 Hi-Res无损。"""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=codec_name,sample_rate,bits_per_raw_sample", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    st = json.loads(out)["streams"][0]
    ok = st.get("codec_name") == "flac" and st.get("sample_rate") == "48000" and st.get("bits_per_raw_sample") == "24"
    if not ok:
        sys.exit(f"音轨不是 FLAC 48kHz/24bit（{st}），B 站不会显示 Hi-Res无损")
    print("音轨检查: FLAC 48kHz/24bit ✓（Hi-Res无损）")


def start_log(w, stages):
    """本次运行的全部输出（含子进程）同时写到 posts/<name>/logs/<时间>_<阶段>.log，终端照常显示。"""
    import time
    logs = w / "logs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{time.strftime('%Y%m%d-%H%M%S')}_{stages[0]}-{stages[-1]}.log"
    tee = subprocess.Popen(["tee", "-a", str(log)], stdin=subprocess.PIPE)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(tee.stdin.fileno(), sys.stdout.fileno())
    os.dup2(tee.stdin.fileno(), sys.stderr.fileno())
    print(f"日志: {log}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="歌曲短名，用于所有文件名，如 bzrp")
    p.add_argument("--url", help="YouTube 链接（download 阶段需要）")
    p.add_argument("--start", help="截取开始时间，如 00:36:37")
    p.add_argument("--end", help="截取结束时间，如 00:40:04")
    p.add_argument("--sub-lang", help="用 YouTube 官方带时间字幕作参考时的语言代码，如 ja；不填就走 Genius 歌词")
    p.add_argument("--genius-url", help="lyrics 阶段：直接指定 Genius 歌词页")
    p.add_argument("--song-title", help="lyrics 阶段：手动指定歌名（自动识别不准时）")
    p.add_argument("--artist", help="lyrics 阶段：手动指定歌手")
    p.add_argument("--cookies-from-browser", help="yt-dlp 需要登录时: chrome / safari / firefox")
    p.add_argument("--cookies", help="cookies.txt 路径")
    p.add_argument("--frame-format", choices=["auto", "png", "jpg"], default="auto",
                   help="中间帧格式，auto 会按磁盘余量选择")
    p.add_argument("--clean-frames", action="store_true",
                   help="（兼容旧参数；帧序列由 workflow_v4/render.py 渲染完删除）")
    p.add_argument("--force", action="store_true", help="覆盖已存在的结果（人声）")
    p.add_argument("--from", dest="from_", choices=STAGES, default=STAGES[0])
    p.add_argument("--to", choices=STAGES, default=STAGES[-1])
    a = p.parse_args()

    w = Song(a.name).mkdirs().dir
    stages = STAGES[STAGES.index(a.from_): STAGES.index(a.to) + 1]
    start_log(w, stages)
    if "download" in stages and not a.url:
        p.error("download 阶段需要 --url")
    if "lyrics" in stages and not a.url and not a.genius_url and not paths(a, w)["txt"].exists() and not a.sub_lang:
        p.error("lyrics 阶段需要 --url 或 --genius-url（或事先放好 posts/<name>/lyrics.txt）")
    for s in stages:
        print(f"\n========== [{s}] ==========", flush=True)
        globals()[f"stage_{s}"](a, w)


if __name__ == "__main__":
    main()
