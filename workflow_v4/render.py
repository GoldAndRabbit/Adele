# -*- coding: utf-8 -*-
"""v4 成品：一首做完（删帧）再做下一首。

每首：
    1) 还没有 exp_v4/：先把 exp_v3 的翻译缓存拷过去（没变的句子中文和审过的一样），跑 v4，和 v3 逐行比对 -> reports/v4_vs_v3.txt
    2) 水印计划 watermark.json 已有就用（审核页预览的就是它），没有才生成
    3) v1 make_mv.py 只做切片 + RIFE 插帧到 60fps（--from interp --to interp）
    4) 渲染：4K + exp_v4/lyrics_zh3.ass（中文诗意版，和审核页默认一致；没有才用 lyrics_zh2.ass 直译版；
       整体提前和审核页默认的「提前 0.8s」一致）+ 左上角 logo
       + 歌曲中间的半透明水印（和审核页预览同样的时间、位置、大小、透明度、淡入淡出、阴影）+ 原样 FLAC 48kHz/24bit
    5) 删 frames_out 和 video_1080.mp4
成品：posts/<name>/post/<name> 4K60FPS Sub-WaterMark.mp4（每首只留这一个版本）

    .venv/bin/python -m workflow_v4.render song:shakira_madrid_2026:37_bzrp_music_sessions_53 post:lose_yourself_2009 ...
    .venv/bin/python -m workflow_v4.render --hold-changed ...   # 这次新跑的 v4 和 v3 有变化：先不渲染，记到 HOLD，最后一起给人看
"""

import json
import os
import shutil
import subprocess
import sys

from workflow_v2.paths import ROOT, VENV_PY, Concert, read_json

LEAD_EXTRA = 0.6   # 字幕文件里已经统一提前 0.2s；审核页默认「提前 0.8s」= 再提前 0.6s
LOGO = ROOT / "assets" / "adele-logo.png"
LOGO_SCALE = 0.10  # 左上角 logo：和 make_mv.py 一样（logo 原图宽 × 0.10，离左上角 15px）
W, H, FPS = 3840, 2160, 60
JPG_FRAME = 0.6e6  # 1080p JPEG(q1) 一帧大约 0.6MB：磁盘预检用（插帧前后的帧 + 4K 成品）
HOLD = ROOT / "concerts" / "render_v4_hold.json"   # --hold-changed 时先不渲染的歌，等人看


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


# ---------------------------------------------------------------- 1) v4

def lines_of(f):
    if not f.exists():
        return []
    return [f"{r['start_ms'] / 1000:7.2f}  {r.get('text') or ''}" for r in json.loads(f.read_text())
            if r.get("verdict") != "unconfirmed" and (r.get("text") or "").strip()]


def keep_reviewed_zh(d):
    """v4 里原文和 v3 一样、时间差不到 1.5 s 的句子，中文（v1 / v2）、幻听判定、顶部注释都沿用 v3（你审过的）；
    只有 v4 对齐真变了的句子用 v4 新翻的。然后重新生成 exp_v4 的字幕（不调模型）。"""
    from .song_translation_workflow import _norm, build_outputs
    f3, f4 = d / "exp_v3" / "translation" / "result.json", d / "exp_v4" / "translation" / "result.json"
    if not f3.exists() or not f4.exists():
        return 0
    r3, r4 = json.loads(f3.read_text()), json.loads(f4.read_text())
    n3 = {int(k): v for k, v in (r3.get("notes") or {}).items()}
    notes, used, kept = {}, set(), 0
    for u in r4["units"]:
        m = min((x for x in r3["units"] if x["i"] not in used and _norm(x["orig"]) == _norm(u["orig"])
                 and abs(x["start"] - u["start"]) < 1500), key=lambda x: abs(x["start"] - u["start"]), default=None)
        if m is None:
            if str(u["i"]) in (r4.get("notes") or {}):
                notes[u["i"]] = r4["notes"][str(u["i"])]
            continue
        used.add(m["i"])
        kept += 1
        u["v1"], u["v2"] = m["v1"], m["v2"]
        u.pop("dropped", None)
        if m.get("dropped"):
            u["dropped"] = m["dropped"]
        if m["i"] in n3:
            notes[u["i"]] = n3[m["i"]]
    r4["notes"] = {str(k): v for k, v in notes.items()}
    r4["title_zh"] = r3.get("title_zh") or r4.get("title_zh")
    f4.write_text(json.dumps(r4, ensure_ascii=False, indent=1))
    build_outputs(d, d / "exp_v4")
    return kept


def ensure_v4(spec, d):
    out = d / "exp_v4"
    if (out / "lyrics_zh2.ass").exists():
        print(f"{d.name}：已有 v4 结果，直接用", flush=True)
        return
    src = d / "exp_v3" / "translation" / "cache.json"
    if src.exists() and not (out / "translation" / "cache.json").exists():
        (out / "translation").mkdir(parents=True, exist_ok=True)
        shutil.copy(src, out / "translation" / "cache.json")
    p = spec.split(":")
    args = ["post", p[1]] if p[0] == "post" else ["song", p[1], p[2]]
    (d / "logs").mkdir(exist_ok=True)
    with open(d / "logs" / "v4_run.log", "w") as log:
        subprocess.run([VENV_PY, "-m", "workflow_v4.run", *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    kept = keep_reviewed_zh(d)
    print(f"{d.name}：{kept} 句中文沿用 v3（审过的）", flush=True)
    import difflib
    diff = list(difflib.unified_diff(lines_of(d / "exp_v3" / "lines.json"), lines_of(out / "lines.json"),
                                     "v3", "v4", lineterm="", n=0))
    (d / "reports").mkdir(exist_ok=True)
    # 中文 v2：同一句原文，v3 和 v4 译法不一样的（同一批里有句子变了，整批会重新翻）
    zh = lambda f: {(u["orig"], round(u["start"] / 1000)): u.get("v2", "") for u in (json.loads(f.read_text())["units"] if f.exists() else [])}
    z3, z4 = zh(d / "exp_v3" / "translation" / "result.json"), zh(out / "translation" / "result.json")
    zdiff = [f"{k[1]:5d}s  {k[0]}\n       v3 {z3[k]}\n       v4 {z4[k]}" for k in z4 if k in z3 and z3[k] != z4[k]]
    (d / "reports").mkdir(exist_ok=True)
    (d / "reports" / "v4_vs_v3.txt").write_text("\n".join(diff) + "\n\n中文 v2 译法变了的句子：\n" + "\n".join(zdiff) + "\n")
    print(f"{d.name}：中文 v2 译法变了 {len(zdiff)} 句", flush=True)
    changed = sum(1 for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---"))
    print(f"{d.name}：v4 跑完，和 v3 相比 {changed} 行有变化（reports/v4_vs_v3.txt）", flush=True)
    return changed


def ensure_watermark(spec, d):
    if (d / "watermark.json").exists():
        return
    p = spec.split(":")
    args = ["post", p[1]] if p[0] == "post" else ["song", p[1], p[2]]
    sh([VENV_PY, "-m", "workflow_v4.watermark", *args], cwd=ROOT)


# ---------------------------------------------------------------- 4) 渲染

def render_ass(d, work):
    import pysubs2
    f = d / "exp_v4" / "lyrics_zh3.ass"   # 诗意版（审核页默认）；没有就用直译版
    subs = pysubs2.load(str(f if f.exists() else d / "exp_v4" / "lyrics_zh2.ass"))
    print(f"{d.name}：字幕用 {'诗意版' if f.exists() else '直译版'}", flush=True)
    ms = round(LEAD_EXTRA * 1000)
    for ev in subs.events:   # 审核页预览是所有字幕一起挪（含片头、注释），这里一样
        ev.start, ev.end = max(0, ev.start - ms), max(0, ev.end - ms)
    subs.save(str(work / "subs_v4.ass"))


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


def render(d, work, out, frames=None, t_in=0.0, enc=None):
    render_ass(d, work)
    wm = read_json(d / "watermark.json", {}) or {}
    items = wm.get("items") or []
    ext = "jpg" if any((work / "frames_out").glob("*.jpg")) else "png"
    if not frames and not any((work / "frames_out").glob(f"*.{ext}")):   # 原片 60 帧、没抽帧：直接读中间视频
        frames, src_fps = ["-i", "video_1080.mp4"], f"setpts=PTS-STARTPTS,fps={FPS},"
    else:
        src_fps = ""
    inputs = (frames or ["-framerate", FPS, "-i", f"frames_out/%08d.{ext}"]) + ["-i", d / "audio.flac", "-i", LOGO]
    shift = src_fps + (f"setpts=PTS+{t_in}/TB," if t_in else "")   # t_in 只给抽查用：从中间某一秒开始的片段，时间对回歌曲内时间
    fc = [f"[0:v]{shift}scale=3840:2160:flags=lanczos,ass=subs_v4.ass[s0]",
          f"[2:v]scale=iw*{LOGO_SCALE}:-1[logo]",
          "[s0][logo]overlay=15:15:format=auto[v0]"]
    last = "v0"
    if items:
        img, pad = wm_image(wm, work)
        for k, it in enumerate(items):
            t0, dur, fade = it["t"], it["dur"], it["fade"]   # 水印按画面时间，不跟字幕提前
            inputs += ["-loop", "1", "-framerate", FPS, "-t", f"{t0 + dur + 1:.3f}", "-i", img]
            fc.append(f"[{3 + k}:v]format=rgba,colorchannelmixer=aa={wm['opacity']},"
                      f"fade=t=in:st={t0:.3f}:d={fade}:alpha=1,fade=t=out:st={t0 + dur - fade:.3f}:d={fade}:alpha=1[w{k}]")
            x, y = round(W * it["x"]) - pad, round(H * it["y"]) - pad
            fc.append(f"[{last}][w{k}]overlay={x}:{y}:format=auto:eof_action=pass:enable='between(t,{t0:.3f},{t0 + dur:.3f})'[v{k + 1}]")
            last = f"v{k + 1}"
    fc.append(f"[{last}]format=yuv420p[v]")
    tmp = out.with_suffix(".partial.mp4")
    sh(["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "1:a",
        *(enc or ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-profile:v", "high", "-level", "5.2"]),
        "-c:a", "copy",   # FLAC 48kHz/24bit 原样放进 mp4：B 站靠它给 Hi-Res无损 标
        "-shortest", "-movflags", "+faststart", tmp], cwd=work)
    tmp.replace(out)
    sys.path.insert(0, str(ROOT / "workflow"))
    from make_mv import check_hires
    check_hires(out)


def check_disk(d, seconds):
    """帧序列 + 4K 成品要的空间（偏保守）。原片已经是 60 帧的不插帧也不抽帧；要插帧的是原生帧 + 60 帧两份。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(d / "source.mp4")], capture_output=True, text=True).stdout.strip() or "30/1"
    num, den = (r.split("/") + ["1"])[:2]
    fps = float(num) / float(den or 1)
    per_sec = 0 if fps >= FPS - 0.5 else fps + FPS   # 60 帧的原片不抽帧，渲染直接读中间视频
    need = seconds * per_sec * JPG_FRAME * 1.3 + seconds * 7e6 + 3e9
    free = shutil.disk_usage(d).free
    if free < need:
        sys.exit(f"磁盘不够：{d.name} 至少要 {need / 1e9:.0f}GB，剩余 {free / 1e9:.0f}GB。清理后重跑，已完成的会跳过")


def one(spec, hold_changed=False):
    d, span, posts = song_of(spec)
    print(f"\n========== {d.name} ==========", flush=True)
    out = d / "post" / f"{d.name} 4K60FPS Sub-WaterMark.mp4"
    if out.exists():
        print(f"已有成品，跳过：{out}", flush=True)
        return
    changed = ensure_v4(spec, d)
    if hold_changed and changed and (d / "exp_v3" / "lines.json").exists():   # 没有 v3（新歌）就没得比，不拦
        raise Skip(f"v4 和 v3 有 {changed} 行不一样，先不渲染，等人看 reports/v4_vs_v3.txt")
    ensure_watermark(spec, d)
    if span and not (d / "source.mp4").exists():   # 整场演唱会的歌：从整场视频切
        (d / "source.mp4").symlink_to(Concert(spec.split(":")[1]).source)
    check_disk(d, (span[1] - span[0]) if span else float(read_json(d / "meta.json", {}).get("duration") or 400))
    env = dict(os.environ, **({"ADELE_POSTS": str(posts)} if posts else {}))
    cmd = [VENV_PY, ROOT / "workflow" / "make_mv.py", "--name", d.name, "--from", "interp", "--to", "interp"]
    if span:
        cmd += ["--start", f"{span[0]:.3f}", "--end", f"{span[1]:.3f}"]
    sh(cmd, env=env, cwd=ROOT)
    (d / "post").mkdir(exist_ok=True)
    render(d, d, out)
    shutil.rmtree(d / "frames_out", ignore_errors=True)   # 帧序列：做完这首就删
    (d / "video_1080.mp4").unlink(missing_ok=True)
    print(f">>> {out}", flush=True)


if __name__ == "__main__":
    hold_changed = "--hold-changed" in sys.argv
    held = json.loads(HOLD.read_text()) if HOLD.exists() else {}
    for spec in [a for a in sys.argv[1:] if not a.startswith("--")]:
        try:
            one(spec, hold_changed)
            held.pop(spec, None)
        except Skip as e:
            print(f"跳过 {spec}：{e}", flush=True)
            held[spec] = str(e)
        except subprocess.CalledProcessError as e:   # 某一步失败：这首跳过，队列接着做
            print(f"跳过 {spec}：出错 {e}", flush=True)
            held[spec] = f"出错：{e}"
        HOLD.parent.mkdir(exist_ok=True)
        HOLD.write_text(json.dumps(held, ensure_ascii=False, indent=1))
    print(f"\n全部结束；先没渲染的 {len(held)} 首：{HOLD}", flush=True)
