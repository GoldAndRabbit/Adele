#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
歌曲链接 -> 4K60 + 水印 + 原文/中文双语字幕 + FLAC Hi-Res 的成品视频。

阶段（可用 --from / --to 断点续跑）:
  download   yt-dlp 下载原视频 + 官方字幕 + 元信息      -> posts/<name>/source.mp4, meta.json
  prep       截取片段、降到 1080p、导出 FLAC 48k/24bit  -> posts/<name>/video_1080.mp4, audio.flac
  lyrics     参考歌词：官方带时间字幕优先（--sub-lang），
             否则 get_ytb_lyrics_from_link.py 从 Genius 取歌词文本 -> posts/<name>/official.srt 或 lyrics.txt
  separate   Mel-Band RoFormer 人声分离（.venv-sep）    -> posts/<name>/vocals.wav
  align      时间轴：官方字幕只做后处理；歌词文本走
             Qwen 演唱序列 -> 分块对齐 -> 推理补句 -> 强制对齐精修 -> 后处理 -> 逐句 Qwen 复核
                                                        -> posts/<name>/lyrics.srt
  translate  DeepSeek 翻译（按句缓存）+ 标题中文行        -> posts/<name>/lyrics.ass
  interp     原生帧率抽帧 + RIFE 一步插到 60fps          -> posts/<name>/frames_out/
  render     4K + 烧字幕 + 水印 + FLAC，渲染后检查音轨   -> posts/<name>/post/<name> 4K60FPS Sub-WaterMark.mp4

用法:
  .venv/bin/python workflow/make_mv.py --name X --url "https://..." --lang ja --title "《歌名》 歌手"
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import BIN, MODELS, ROOT, WORKFLOW as PIPE, Song  # noqa: E402

VENV_BIN = ROOT / ".venv" / "bin"
SEP_PY = ROOT / ".venv-sep" / "bin" / "python"
STAGES = ["download", "prep", "lyrics", "separate", "align", "translate", "interp", "render"]
LANG_CODES = {"english": "en", "japanese": "ja", "spanish": "es", "chinese": "zh", "italian": "it"}
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
        keep = {k: d.get(k) for k in ("title", "channel", "duration", "language", "track", "artist",
                                    "upload_date", "description", "tags", "webpage_url")}
        (w / "meta.json").write_text(json.dumps(keep, ensure_ascii=False, indent=2))


def make_1080(a, w):
    """统一降到 1080p 再插帧（4K 直接插帧太慢、太占盘）；帧率保持原生，后面交给 RIFE。"""
    trim = (["-ss", a.start] if a.start else []) + (["-to", a.end] if a.end else [])
    tmp = w / "video_1080.partial.mp4"
    run(["ffmpeg", "-y", "-hide_banner", *trim, "-i", w / "source.mp4",
         "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
         "-an", "-c:v", "libx264", "-crf", "12", "-preset", "fast", "-pix_fmt", "yuv420p", tmp])
    tmp.replace(w / "video_1080.mp4")  # 写完整才改名：中途被停不会留下半截文件


def video_1080_ok(a, w):
    """1080p 中间视频存在且时长和源视频（截取后）一致。"""
    v = w / "video_1080.mp4"
    if not v.exists():
        return False
    src = probe(w / "source.mp4")["duration"]
    if a.start or a.end:
        src = (to_seconds(a.end) if a.end else src) - (to_seconds(a.start) or 0)
    return abs(probe(v)["duration"] - src) < 1.0


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


def lang_code(a):
    l = (a.lang or "en").lower()
    return LANG_CODES.get(l, l)


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


CJK_LANGS = {"ja", "zh", "ko"}


def maybe_split(a, py, srt, voc):
    """歌词一行就显示一行（尊重歌词的分行）。只有日文/中文这类没有空格、渲染时没法自动换行的长句，
    才在歌词自带的全角空格处拆开；英文/意大利语等长行交给字幕渲染自动换行 + 缩小字号。"""
    if lang_code(a) in CJK_LANGS:
        run([py, PIPE / "split_long.py", srt, "--vocals", voc, "--max-width", a.max_width])


def stage_align(a, w):
    """时间轴。文字只来自参考歌词（官方字幕 / Genius 文本），识别结果只用来定位和复核。"""
    p = paths(a, w)
    py, lang, voc, srt = sys.executable, lang_code(a), p["vocals"], p["srt"]
    source = p["source"].read_text().strip() if p["source"].exists() else "reference"
    common = ["--vocals", voc, "--lang", lang]

    if source == "official":
        # 官方时间轴是人工打的，实测任何重解码都会变差：只拆长句 + 拖音/短空档桥接/句尾收紧
        ref = Song(a.name).official_srt
        maybe_split(a, py, srt, voc)
        run([py, PIPE / "acoustic.py", srt, "--ref", ref, *common, "--mode", "post", "-o", srt,
             "--report", w / "reports" / "acoustic_report.json"])
        return

    ref = p["txt"]
    if a.align_mode == "lyrics":
        # 歌词主导（说唱等 ASR 难识别、但基本按原词唱的歌）：整首歌词按顺序强制对齐，识别只用来复核、不换句
        run([py, PIPE / "lyrics_align.py", "--ref", ref, *common, "-o", srt, "--report", w / "reports" / "lyrics_align.json"])
        maybe_split(a, py, srt, voc)
        run([py, PIPE / "refine_timing.py", srt, *common, "--lead", a.lead,
             "-o", srt, "--report", w / "reports" / "timing_report.json"])
        run([py, PIPE / "acoustic.py", srt, "--ref", ref, *common, "--mode", "post", "--no-fill-gaps",
             "-o", srt, "--report", w / "reports" / "acoustic_report.json"])
        run([py, PIPE / "verify_qwen.py", srt, "--ref", ref, *common, "--no-swap",
             "-o", srt, "--report", w / "reports" / "verify_report.json"])
        maybe_split(a, py, srt, voc)
        print(f"\n>>> 字幕（歌词主导）: {srt}")
        return
    order, order_rep = w / "reports" / "sung_order.txt", w / "reports" / "sung_order.json"
    # 1) Qwen3-ASR 分块识别 -> 这一版实际演唱的句子顺序 + 每句所在时间块
    run([py, PIPE / "qwen_sequence.py", "--ref", ref, *common, "-o", order, "--report", order_rep])
    # 2) 分块对齐：每块的句子序列，在块的时间范围里用 MMS 按顺序强制对齐
    run([py, PIPE / "chunk_align.py", "--order", order, "--chunks", order_rep, *common, "-o", srt])
    maybe_split(a, py, srt, voc)
    # 3) 先推理补句（空档还在的时候），再精修和后处理——顺序反了，拖音会先把空档盖住
    run([py, PIPE / "infer_insert.py", srt, "--ref", ref, *common, "--no-neighbor-fix",
         "-o", srt, "--report", w / "reports" / "infer_report.json"])
    run([py, PIPE / "refine_timing.py", srt, *common, "--lead", a.lead,
         "-o", srt, "--report", w / "reports" / "timing_report.json"])
    run([py, PIPE / "acoustic.py", srt, "--ref", ref, *common, "--mode", "post", "--no-fill-gaps",
         "-o", srt, "--report", w / "reports" / "acoustic_report.json"])
    # 4) 逐句 Qwen 复核：明显是别的句子就换，明确不对的隐藏
    run([py, PIPE / "verify_qwen.py", srt, "--ref", ref, *common, "-o", srt, "--report", w / "reports" / "verify_report.json"])
    maybe_split(a, py, srt, voc)
    print(f"\n>>> 字幕: {srt}；可疑句见 {w / 'reports' / 'verify_report.json'}")


TITLE_PROMPT = """从 YouTube 视频标题里提取演唱的歌名和歌手，输出 JSON {"title": "《歌名》 歌手"}。
- 只用标题和简介里明确写出的信息，不要猜；歌名、歌手保持原文写法
- 多首歌（串烧）用 " / " 分隔，按标题里的顺序：《歌1 / 歌2》 歌手
- 去掉节目名、日期、频道名、Official Video / Live / 4K / Lyrics 等标签；合作歌手用 " & " 连接"""


def auto_title(w):
    """字幕首行标题：默认从 YouTube 视频标题提取（LLM 整理成《歌名》 歌手），结果存 title.txt 可手改。"""
    cached = w / "title.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8").strip()
    meta = json.loads((w / "meta.json").read_text()) if (w / "meta.json").exists() else {}
    if not meta.get("title"):
        return None
    from llm import chat_json
    src = f"标题: {meta['title']}\n频道: {meta.get('channel', '')}\n简介开头: {(meta.get('description') or '')[:300]}"
    title = chat_json(TITLE_PROMPT, src, temperature=0, label="标题提取").get("title", "").strip() or meta["title"]
    cached.write_text(title + "\n", encoding="utf-8")
    print(f"字幕标题（来自 YouTube 标题，可改 {cached}）: {title}")
    return title


def stage_translate(a, w):
    src, out = Song(a.name).lyrics_srt, Song(a.name).lyrics_ass
    if out.exists() and not a.force:
        print(f"已存在 {out}（人工校对过的不会被覆盖，--force 可重新生成）")
        return
    title = a.title or auto_title(w)
    cmd = [sys.executable, PIPE / "translate_ass.py", src, "-o", out,
           "--cache", w / "zh_cache.json"]
    if title:
        cmd += ["--title", title]
    if a.zh_file:
        cmd += ["--zh-file", a.zh_file]
    cmd += ["--style", a.sub_style]
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
    if not a.keep_frames:
        shutil.rmtree(fin)


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


def stage_render(a, w):
    ass = Path(a.ass).resolve() if a.ass else Song(a.name).lyrics_ass
    if not ass.exists():
        sys.exit(f"缺少字幕 {ass}")
    # ass 滤镜对路径里的空格/冒号转义很麻烦，拷到工作目录用相对路径
    shutil.copy(ass, w / "subs.ass")
    if a.sub_shift:
        # 整体提前/推后字幕（人眼对画面变化反应快，提前一点看起来更跟手）；标题行不动
        import pysubs2
        subs = pysubs2.load(str(w / "subs.ass"))
        ms = int(a.sub_shift * 1000)
        for ev in subs.events:
            if ev.style == "Default" and ev.start > 0:
                ev.start, ev.end = max(0, ev.start - ms), max(0, ev.end - ms)
        subs.save(str(w / "subs.ass"))
        print(f"字幕整体提前 {a.sub_shift}s")
    out = Song(a.name).video(a.tag)
    ext = "jpg" if any((w / "frames_out").glob("*.jpg")) else "png"

    if a.fast:
        venc = ["-c:v", "hevc_videotoolbox", "-q:v", "70", "-tag:v", "hvc1"]
    else:
        venc = ["-c:v", "libx264", "-crf", str(a.crf), "-preset", "medium",
                "-profile:v", "high", "-level", "5.2"]

    run(["ffmpeg", "-y", "-hide_banner",
         "-framerate", TARGET_FPS, "-i", f"frames_out/%08d.{ext}",
         "-i", Song(a.name).audio,
         "-i", ROOT / a.logo,
         "-filter_complex",
         "[0:v]scale=3840:2160:flags=lanczos,ass=subs.ass[sub];"
         f"[2:v]scale=iw*{a.logo_scale}:-1[wm];"
         "[sub][wm]overlay=15:15:format=auto,format=yuv420p[v]",
         "-map", "[v]", "-map", "1:a",
         *venc,
         # 必须是 FLAC（48kHz/24bit）原样放进 mp4：B 站靠它给 “Hi-Res无损” 标，不要改成 AAC
         "-c:a", "copy",
         "-shortest", "-movflags", "+faststart",
         out], cwd=w)
    check_hires(out)
    print(f"\n>>> 成品: {out}")
    if not a.keep_frames:
        shutil.rmtree(w / "frames_out", ignore_errors=True)


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
    p.add_argument("--lang", help="演唱语言：ja / en / es ...（Qwen 识别和强制对齐用）")
    p.add_argument("--sub-lang", help="用 YouTube 官方带时间字幕作参考时的语言代码，如 ja；不填就走 Genius 歌词")
    p.add_argument("--genius-url", help="lyrics 阶段：直接指定 Genius 歌词页")
    p.add_argument("--song-title", help="lyrics 阶段：手动指定歌名（自动识别不准时）")
    p.add_argument("--artist", help="lyrics 阶段：手动指定歌手")
    p.add_argument("--max-width", type=int, default=40, help="单句最大显示宽度（全角算 2），超过就拆")
    p.add_argument("--align-mode", choices=["qwen", "lyrics"], default="qwen",
                   help="qwen：Qwen 识别演唱顺序（现场改编/删减多的歌）；lyrics：以歌词顺序为准只对时间（说唱等 ASR 难识别的歌）")
    p.add_argument("--lead", type=float, default=0.12, help="字幕比开口提前出现的秒数（align 阶段）")
    p.add_argument("--title", help="字幕首行标题，如 '《Song》 Artist'；不填就从 YouTube 标题自动提取（存 title.txt，可手改）")
    p.add_argument("--sub-style", choices=["bzrp", "modern"], default="bzrp",
                   help="字幕样式：bzrp=与 bzrp_v2.ass 相同（默认）；modern=1080p 画布、日文粗体、标题在顶部")
    p.add_argument("--zh-file", help="不调 API，直接用这个文件里的中文翻译（每行对应一句）")
    p.add_argument("--cookies-from-browser", help="yt-dlp 需要登录时: chrome / safari / firefox")
    p.add_argument("--cookies", help="cookies.txt 路径")
    p.add_argument("--ass", help="render 用的字幕文件，默认 posts/<name>/lyrics.ass")
    p.add_argument("--tag", help="成品文件名后缀，用于对比不同版本，如 bzrpv2style")
    p.add_argument("--sub-shift", type=float, default=0.2,
                   help="渲染时字幕整体再提前的秒数（叠加在 --lead 0.12 之上，默认 0.2，实测最舒服）")
    p.add_argument("--logo", default="assets/adele-logo.png")
    p.add_argument("--logo-scale", default="0.10")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--fast", action="store_true", help="用 VideoToolbox HEVC 硬编，快很多")
    p.add_argument("--frame-format", choices=["auto", "png", "jpg"], default="auto",
                   help="中间帧格式，auto 会按磁盘余量选择")
    p.add_argument("--keep-frames", action="store_true", help="保留 PNG 帧（默认渲染后删除，很占盘）")
    p.add_argument("--force", action="store_true", help="覆盖已存在的结果（人声、双语字幕）")
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
