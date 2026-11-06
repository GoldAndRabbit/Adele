# -*- coding: utf-8 -*-
"""成品：按顺序一首一首做，插帧和编码错开一首（流水线）。

流水线：第 i 首在编码（ffmpeg，苹果硬件编码时走媒体引擎）的同时，第 i+1 首已经开始插帧（RIFE，走 GPU）。
任何时候最多 1 首在插帧、1 首在编码，所以磁盘上最多两首的帧（帧一律 JPEG q1，一首 4~5 分钟约 10GB）；插帧模型同一时间只开一个。
第 i+1 首插完帧，要等第 i 首编码完才开始编码（顺序不乱）。磁盘不够放下一首的帧时，先等正在编码的那首做完（删了帧）再检查。
ffmpeg 编码的输出写进这首的 logs/render_<时间>.log，终端只打开始 / 结束，两首的输出不会搅在一起。

每首：
    1) 还没有 subs/ 就先跑字幕流程（workflow.song.run：对齐 / 观众合唱 / 翻译 / 注释）
    2) 水印计划 watermark.json 已有就用（审核页预览的就是它），没有才生成
    3) workflow/make_mv.py 只做切片 + RIFE 插帧到 60fps（--from interp --to interp；原片已经是 60 帧的不插帧也不抽帧）
    4) 渲染：4K + subs/lyrics_poetic.ass（中文诗意版，和审核页默认一致；没有才用 lyrics_literal.ass 直译版；
       整体提前和审核页默认的「提前 0.8s」一致）+ 左上角 logo（宽银幕片源放在画面内容的左上角，不放在黑边上；片源左上角有台标的场次放右上角）
       + 歌曲中间的半透明水印（和审核页预览同样的时间、位置、大小、透明度、淡入淡出、阴影）+ 原样 FLAC 48kHz/24bit
    5) 删 frames_out 和 video_1080.mp4（编码完这首就删）
成品：posts/<场次>/<name>/post/<name> 4K60FPS Sub-WaterMark.mp4（单曲是 posts/<name>/post/；每首只留这一个版本）

    .venv/bin/python -m workflow.song.render song:lorde_acl2026:01_royals post:lose_yourself_2009 ...
    .venv/bin/python -m workflow.song.render --enc hevc_hw song:...   # 显式选择默认的苹果 HEVC 硬件编码

编码器：默认 hevc_hw（苹果 VideoToolbox HEVC/H.265，35 Mbps，峰值 50 Mbps）。
可用 --enc x264 选择软件 H.264，或 --enc h264_hw 选择苹果硬件 H.264。
"""

import os
import shutil
import subprocess
import sys

from workflow.paths import render_subtitle
from workflow.live.paths import ROOT, VENV_PY, Concert, read_json

LEAD_EXTRA = 0.6   # 字幕文件里已经统一提前 0.2s；审核页默认「提前 0.8s」= 再提前 0.6s
LOGO = ROOT / "assets" / "adele-logo.png"
W, H, FPS = 3840, 2160, 60
DEFAULT_ENCODER = "hevc_hw"
ENCODERS = {   # 成品视频编码参数（--enc）；硬件的码率是和 x264 crf 18 肉眼看不出差别的取值（Levitating 实测）
    "x264": ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-profile:v", "high", "-level", "5.2"],
    "h264_hw": ["-c:v", "h264_videotoolbox", "-b:v", "50M", "-maxrate", "70M", "-bufsize", "100M", "-profile:v", "high", "-level", "5.2"],
    "hevc_hw": ["-c:v", "hevc_videotoolbox", "-b:v", "35M", "-maxrate", "50M", "-bufsize", "70M", "-profile:v", "main", "-tag:v", "hvc1"],
}
JPG_FRAME = 0.6e6  # 1080p JPEG(q1) 一帧大约 0.6MB：磁盘预检用（插帧前后的帧 + 4K 成品）


class Skip(Exception):
    """这一首跳过（写明原因），队列接着做下一首。"""


def sh(cmd, **kw):
    print("$", " ".join(str(x) for x in cmd), flush=True)
    subprocess.run([str(x) for x in cmd], check=True, **kw)


def song_of(spec):
    """song:slug:name / post:name -> (歌曲目录, 切片起止或 None, make_mv 用的 ADELE_POSTS)"""
    p = spec.split(":")
    if p[0] == "post":
        return ROOT / "posts" / p[1], None, None
    c = Concert(p[1])
    it = c.item(p[2])
    d = c.song_dir(it)
    seg = next(s for s in c.load("segments")["items"] if s["name"] == it["name"])
    info = read_json(d / "song.json", {})
    if info.get("slice") != [round(seg["start"], 2), round(seg["end"], 2)]:
        raise Skip(f"片段音频 {info.get('slice')} 和边界 {seg['start']}~{seg['end']} 对不上，先处理")
    return d, (seg["start"], seg["end"]), c.songs


# ---------------------------------------------------------------- 1) 字幕

def ensure_subs(spec, d):
    if (d / "subs" / "lyrics_literal.ass").exists():
        print(f"{d.name}：已有字幕结果，直接用", flush=True)
        return
    p = spec.split(":")
    args = ["post", p[1]] if p[0] == "post" else ["song", p[1], p[2]]
    (d / "logs").mkdir(exist_ok=True)
    with open(d / "logs" / "v4_run.log", "w") as log:
        subprocess.run([VENV_PY, "-m", "workflow.song.run", *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)


def ensure_watermark(spec, d):
    if (d / "watermark.json").exists():
        return
    p = spec.split(":")
    args = ["post", p[1]] if p[0] == "post" else ["song", p[1], p[2]]
    sh([VENV_PY, "-m", "workflow.song.watermark", *args], cwd=ROOT)


# ---------------------------------------------------------------- 4) 渲染

def render_ass(d, work):
    import pysubs2
    f = render_subtitle(d)
    subs = pysubs2.load(str(f))
    print(f"{d.name}：字幕用 {'诗意版' if f.name == 'lyrics_poetic.ass' else '直译版'}", flush=True)
    import re
    for event in subs.events:
        event.text = r"\N".join(
            re.sub("[♪♫♬🎵🎶]", "", line).strip() if re.search("[\u3400-\u9fff]", line) else line
            for line in event.text.split(r"\N"))
    ms = round(LEAD_EXTRA * 1000)
    for ev in subs.events:   # 审核页预览是所有字幕一起挪（含片头、注释），这里一样
        ev.start, ev.end = max(0, ev.start - ms), max(0, ev.end - ms)
    subs.save(str(work / "burn.ass"))


def wm_image(wm, work):
    """水印图：宽 = 画面宽 × width；带和审核页一样的两圈淡深色阴影（2px 55%、6px 35%），四周留边，返回 (路径, 留边)。"""
    from PIL import Image, ImageFilter
    logo = Image.open(LOGO).convert("RGBA")
    w = round(W * wm["width"])
    logo = logo.resize((w, round(logo.height * w / logo.width)), Image.LANCZOS)
    pad = 16
    canvas = Image.new("RGBA", (logo.width + 2 * pad, logo.height + 2 * pad), (0, 0, 0, 0))
    a = Image.new("L", canvas.size, 0)
    a.paste(logo.getchannel("A"), (pad, pad))
    for r, k in ((6, 0.35), (2, 0.55)):   # 先画大的淡阴影，再画小的
        sh_a = a.filter(ImageFilter.GaussianBlur(r)).point(lambda v, k=k: round(v * k))
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.putalpha(sh_a)
        canvas = Image.alpha_composite(canvas, layer)
    canvas.alpha_composite(logo, (pad, pad))
    f = work / "_wm.png"
    canvas.save(f)
    return f, pad


def render(d, work, out, frames=None, t_in=0.0, enc=None, log=None):
    render_ass(d, work)
    wm = read_json(d / "watermark.json", {}) or {}
    items = wm.get("items") or []
    ext = "jpg" if any((work / "frames_out").glob("*.jpg")) else "png"
    if not frames and not any((work / "frames_out").glob(f"*.{ext}")):   # 原片 60 帧、没抽帧：直接读中间视频
        frames, src_fps = ["-i", "video_1080.mp4"], f"setpts=PTS-STARTPTS,fps={FPS},"
    else:
        src_fps = ""
    inputs = (frames or ["-framerate", FPS, "-i", f"frames_out/%08d.{ext}"]) + ["-i", d / "audio.flac"]
    shift = src_fps + (f"setpts=PTS+{t_in}/TB," if t_in else "")   # t_in 只给抽查用：从中间某一秒开始的片段，时间对回歌曲内时间
    fc = [f"[0:v]{shift}scale=3840:2160:flags=lanczos,ass=burn.ass[v0]"]
    last = "v0"
    if items:
        img, pad = wm_image(wm, work)
        for k, it in enumerate(items):
            t0, dur, fade = it["t"], it["dur"], it["fade"]   # 水印按画面时间，不跟字幕提前
            inputs += ["-loop", "1", "-framerate", FPS, "-t", f"{t0 + dur + 1:.3f}", "-i", img]
            fc.append(f"[{2 + k}:v]format=rgba,colorchannelmixer=aa={wm['opacity']},"
                      f"fade=t=in:st={t0:.3f}:d={fade}:alpha=1,fade=t=out:st={t0 + dur - fade:.3f}:d={fade}:alpha=1[w{k}]")
            x, y = round(W * it["x"]) - pad, round(H * it["y"]) - pad
            fc.append(f"[{last}][w{k}]overlay={x}:{y}:format=auto:eof_action=pass:enable='between(t,{t0:.3f},{t0 + dur:.3f})'[v{k + 1}]")
            last = f"v{k + 1}"
    fc.append(f"[{last}]format=yuv420p[v]")
    tmp = out.with_suffix(".partial.mp4")
    cmd = ["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "1:a",
           *(enc or ENCODERS[DEFAULT_ENCODER]),
           "-c:a", "copy",   # FLAC 48kHz/24bit 原样放进 mp4：B 站靠它给 Hi-Res无损 标
           "-shortest", "-movflags", "+faststart", tmp]
    if log is None:
        sh(cmd, cwd=work)
    else:   # 流水线里：编码输出进日志文件（同时另一首在插帧，终端不混）
        with open(log, "a") as fh:
            fh.write("$ " + " ".join(str(x) for x in cmd) + "\n")
            fh.flush()
            subprocess.run([str(x) for x in cmd], check=True, cwd=work, stdout=fh, stderr=subprocess.STDOUT)
    tmp.replace(out)
    sys.path.insert(0, str(ROOT / "workflow"))
    from make_mv import check_hires
    check_hires(out)


def disk_need(d, seconds):
    """帧序列 + 4K 成品要的空间（偏保守）。原片已经是 60 帧的不插帧也不抽帧；要插帧的是原生帧 + 60 帧两份。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(d / "source.mp4")], capture_output=True, text=True).stdout.strip() or "30/1"
    num, den = (r.split("/") + ["1"])[:2]
    fps = float(num) / float(den or 1)
    per_sec = 0 if fps >= FPS - 0.5 else fps + FPS   # 60 帧的原片不抽帧，渲染直接读中间视频
    return seconds * per_sec * JPG_FRAME * 1.3 + seconds * 7e6 + 3e9


def song_seconds(d, span):
    return (span[1] - span[0]) if span else float(read_json(d / "meta.json", {}).get("duration") or 400)


def prepare(spec, reserve=0.0, wait_encode=None):
    """插帧前的所有步骤 + 插帧。返回 (d, out, 时长秒)，已有成品返回 None。
    reserve：正在编码的那首还要写多少（4K 成品，字节）；磁盘不够时先 wait_encode() 等它做完再算一次。"""
    d, span, posts = song_of(spec)
    print(f"\n========== {d.name} ==========", flush=True)
    out = d / "post" / f"{d.name} 4K60FPS Sub-WaterMark.mp4"
    if out.exists():
        print(f"已有成品，跳过：{out}", flush=True)
        return None
    ensure_subs(spec, d)
    ensure_watermark(spec, d)
    if span and not (d / "source.mp4").exists():   # 整场演唱会的歌：从整场视频切
        (d / "source.mp4").symlink_to(Concert(spec.split(":")[1]).source)
    seconds = song_seconds(d, span)
    need = disk_need(d, seconds)
    if shutil.disk_usage(d).free - reserve < need and wait_encode:
        print(f"{d.name}：磁盘紧，先等正在编码的那首做完", flush=True)
        wait_encode()
        reserve = 0.0
    free = shutil.disk_usage(d).free - reserve
    if free < need:
        raise Skip(f"磁盘不够：至少要 {need / 1e9:.0f}GB，剩余 {free / 1e9:.0f}GB。清理后重跑，已完成的会跳过")
    env = dict(os.environ, **({"ADELE_POSTS": str(posts)} if posts else {}))
    # 帧一律用高质量 JPEG（q1，源本身是 4:2:0，肉眼无损）：PNG 一首 4 分半就 32GB，流水线里两首的帧放不下
    cmd = [VENV_PY, ROOT / "workflow" / "make_mv.py", "--name", d.name, "--from", "interp", "--to", "interp", "--frame-format", "jpg"]
    if span:
        cmd += ["--start", f"{span[0]:.3f}", "--end", f"{span[1]:.3f}"]
    sh(cmd, env=env, cwd=ROOT)
    return d, out, seconds


def finish(d, out, enc=DEFAULT_ENCODER):
    """编码成 4K 成品，做完删这首的帧和中间视频。"""
    import time
    (d / "post").mkdir(exist_ok=True)
    (d / "logs").mkdir(exist_ok=True)
    log = d / "logs" / f"render_{time.strftime('%Y%m%d-%H%M%S')}.log"
    print(f"{time.strftime('%H:%M:%S')} {d.name}：开始编码（输出在 {log.relative_to(ROOT)}）", flush=True)
    render(d, d, out, enc=ENCODERS[enc], log=log)
    shutil.rmtree(d / "frames_out", ignore_errors=True)   # 帧序列：编码完这首就删
    (d / "video_1080.mp4").unlink(missing_ok=True)
    print(f"{time.strftime('%H:%M:%S')} {d.name}：编码完成 >>> {out}", flush=True)


def one(spec, enc=DEFAULT_ENCODER):
    """单独做一首（不走流水线）：抽查、补做用。"""
    r = prepare(spec)
    if r:
        finish(r[0], r[1], enc=enc)


def pipeline(specs, enc=DEFAULT_ENCODER):
    """按顺序做；第 i 首编码时第 i+1 首插帧。返回 {spec: 跳过原因}。"""
    from concurrent.futures import ThreadPoolExecutor
    skipped, pending = {}, None   # pending = (spec, future, 预计成品大小)
    pool = ThreadPoolExecutor(max_workers=1)   # 编码只开一个

    def wait_encode():
        nonlocal pending
        if pending:
            spec, fut, _ = pending
            pending = None
            try:
                fut.result()
            except (Exception, SystemExit) as e:   # 编码失败 / Hi-Res 检查不过：这首记下，队列接着做
                print(f"跳过 {spec}：编码出错 {e}", flush=True)
                skipped[spec] = f"编码出错：{e}"

    for spec in specs:
        try:
            r = prepare(spec, reserve=pending[2] if pending else 0.0, wait_encode=wait_encode)
        except Skip as e:
            print(f"跳过 {spec}：{e}", flush=True)
            skipped[spec] = str(e)
            continue
        except (Exception, SystemExit) as e:   # 插帧等某一步失败（如 RIFE 崩溃）：这首跳过，队列接着做
            print(f"跳过 {spec}：出错 {e}", flush=True)
            skipped[spec] = f"出错：{e}"
            continue
        if not r:
            continue
        wait_encode()   # 上一首编码完才开始这一首的编码：同一时间只有一首在编码，成品按顺序出
        d, out, seconds = r
        pending = (spec, pool.submit(finish, d, out, enc), seconds * 7e6)   # 预计成品大小：和 disk_need 一样按 7MB/s 算
    wait_encode()
    pool.shutdown()
    return skipped


if __name__ == "__main__":
    args = sys.argv[1:]
    enc = DEFAULT_ENCODER
    if "--enc" in args:   # --enc x264 / h264_hw / hevc_hw
        k = args.index("--enc")
        enc = args[k + 1]
        del args[k:k + 2]
        if enc not in ENCODERS:
            sys.exit(f"--enc 只能是 {' / '.join(ENCODERS)}")
    skipped = pipeline(args, enc)
    print(f"\n全部结束；跳过 {len(skipped)} 首" + "".join(f"\n  {k}：{v}" for k, v in skipped.items()), flush=True)
