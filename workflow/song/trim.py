# -*- coding: utf-8 -*-
"""
单曲整体从某一秒开始（去掉片头的讲话 / 广告等），不重新识别、对齐和翻译：

    .venv/bin/python -m workflow.song.trim posts/bayern_forever_number_one 32            # 从 32 s 开始
    .venv/bin/python -m workflow.song.trim posts/bayern_forever_drone 0 --end 101        # 到 1:41 结束（END 是现在视频里的时间）

    1) 原视频改名留底 source_full.mp4（再裁一次也从它开始算），从 START 秒精确截出新的 source.mp4
       （重新编码，x264 crf 12，接近无损；4K 成品本来就要从它重新编码）
    2) audio.flac（48k/24bit 不变）和 vocals.wav 从 START 秒按采样精确截取，和画面严格同步
    3) 字幕：逐句数据 lines.json、翻译 translation/result.json（含注释）、观众合唱段 crowd.json、srt 全部平移 −START 秒；
       开始时间早于 START 的句子去掉（不截半句）；按旧时间轴算的识别缓存 asr_words_*.json 删掉；重新生成双语字幕
    4) 只裁结尾：已有的 4K 成品直接截短（-c copy，前面一帧不变），不重新渲染；
       开头改了：水印计划按新长度重做，4K 成品要重新渲染
改之前的 subs/ 备份到 reports/before_trim_<时间>/。审核页的预览视频要重新切：删掉后再跑 workflow.live.singles。
已经裁过的（trim.json 记着上次从第几秒开始）可以再裁：视频、音频照样从原片的 START 秒截，字幕只平移和上次的差值。
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pysubs2


def run(cmd):
    subprocess.run([str(x) for x in cmd], check=True)


def cut_media(d, start, end=None):
    """从原片的 start 秒截到 end 秒（end=None 到结尾；都是原片时间）。"""
    to = ["-t", f"{end - start:.3f}"] if end else []
    full = d / "source_full.mp4"
    if not full.exists():
        (d / "source.mp4").rename(full)
    tmp = d / "source.partial.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", full, *to, "-map", "0:v:0", "-map", "0:a:0?",
         "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k",
         "-movflags", "+faststart", tmp])
    tmp.replace(d / "source.mp4")
    for name, codec in (("audio.flac", ["-c:a", "flac", "-sample_fmt", "s32", "-ar", "48000"]), ("vocals.wav", ["-c:a", "pcm_s16le"])):
        f = d / name
        if not f.exists():
            continue
        full_a = d / f"{f.stem}_full{f.suffix}"
        if not full_a.exists():
            f.rename(full_a)
        tmp = d / f"{f.stem}.partial{f.suffix}"
        run(["ffmpeg", "-v", "error", "-y", "-i", full_a, "-ss", f"{start:.3f}", *to, *codec, tmp])
        tmp.replace(f)


def shift_subs(d, start, end=None):
    """字幕平移 −start 秒；end（平移后的新时间）之后开始的句子去掉，跨过 end 的截到 end。"""
    out = d / "subs"
    ms = round(start * 1000)
    end_ms = round(end * 1000) if end else None
    keep = lambda s: s >= ms and (end_ms is None or s - ms < end_ms)   # 开始早于裁剪点 / 晚于结尾的句子不要（不截半句）
    clip = lambda e: min(e, end_ms) if end_ms else e
    L = json.loads((out / "lines.json").read_text())
    L = [{**r, "start_ms": r["start_ms"] - ms, "end_ms": clip(r["end_ms"] - ms)} for r in L if keep(r["start_ms"])]
    (out / "lines.json").write_text(json.dumps(L, ensure_ascii=False, indent=1))
    tf = out / "translation" / "result.json"
    R = json.loads(tf.read_text())
    old = R["units"]
    units, remap = [], {}
    for u in old:
        if keep(u["start"]):
            remap[u["i"]] = len(units)
            units.append({**u, "start": u["start"] - ms, "end": clip(u["end"] - ms), "i": len(units)})
    R["units"] = units
    for k in ("notes", "final_notes"):
        if R.get(k):
            R[k] = {str(remap[int(i)]): v for i, v in R[k].items() if int(i) in remap}
    tf.write_text(json.dumps(R, ensure_ascii=False, indent=1))
    cf = out / "crowd.json"
    if cf.exists():
        C = json.loads(cf.read_text())
        C["segments"] = [{**s, "s": round(s["s"] - start, 2), "e": round(min(s["e"] - start, end or 1e9), 2)}
                         for s in C.get("segments", []) if s["s"] >= start and (end is None or s["s"] - start < end)]
        cf.write_text(json.dumps(C, ensure_ascii=False, indent=1))
    for name in ("lyrics.srt", "speech.srt"):
        f = out / name
        if f.exists() and f.read_text().strip():   # 没有讲话时 speech.srt 是空文件
            subs = pysubs2.load(str(f))
            subs.events = [e for e in subs.events if e.start >= ms and (end_ms is None or e.start - ms < end_ms)]
            subs.shift(ms=-ms)
            for e in subs.events:
                e.end = clip(e.end)
            subs.save(str(f))
    for f in out.glob("asr_words_*.json"):   # 识别缓存按旧时间轴：要重跑这首时重新识别
        f.unlink()
    return len(L), len(units)


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("song_dir")
    p.add_argument("start", type=float, help="从原片的第几秒开始（不改开头就填上次的值，第一次裁填 0）")
    p.add_argument("--end", type=float, help="到第几秒结束：现在视频里看到的时间（裁完开头之后的时间）")
    a = p.parse_args()
    d, start = Path(a.song_dir), a.start
    prev = json.loads((d / "trim.json").read_text()) if (d / "trim.json").exists() else {"start": 0.0}
    if start < prev["start"] or (start == prev["start"] and a.end is None):
        sys.exit(f"已经从 {prev['start']:g} s 开始了；开头只能往后裁（START 要大于 {prev['start']:g}），或者加 --end 裁结尾")
    end_full = prev["start"] + a.end if a.end is not None else prev.get("end")   # 换算成原片时间
    if end_full is not None and end_full <= start:
        sys.exit("结尾早于开头")
    bak = d / "reports" / f"before_trim_{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(d / "subs", bak / "subs")
    for f in ("watermark.json",):
        if (d / f).exists():
            shutil.copy(d / f, bak / f)
    cut_media(d, start, end_full)
    # 字幕已经按上次的起点平移过：只移差值；结尾换算成平移后的新时间
    n_lines, n_units = shift_subs(d, start - prev["start"], end_full - start if end_full is not None else None)
    (d / "trim.json").write_text(json.dumps({"start": start, "end": end_full}) + "\n")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from workflow.song.song_translation_workflow import build_outputs
    build_outputs(d, d / "subs")
    final = d / "post" / f"{d.name} 4K60FPS Sub-WaterMark.mp4"
    if start == prev["start"] and end_full is not None and final.exists():
        # 只裁结尾：成品前面一帧不变（字幕、水印都烧在画面里），直接截短，不用重新渲染；水印计划也不动
        tmp = final.with_suffix(".partial.mp4")
        run(["ffmpeg", "-v", "error", "-y", "-i", final, "-t", f"{end_full - start:.3f}", "-map", "0", "-c", "copy",
             "-movflags", "+faststart", tmp])
        tmp.replace(final)
        print(f"只裁结尾：4K 成品直接截到 {end_full - start:.1f} s，没有重新渲染")
    else:   # 开头动了：字幕整体前移、要从某一帧精确开始，成品得重新渲染；水印计划按新长度重做
        (d / "watermark.json").unlink(missing_ok=True)
        run([sys.executable, "-m", "workflow.song.watermark", "post", d.name])
        if final.exists():
            print(f"开头改了：4K 成品要重新渲染（workflow.song.render post:{d.name}）")
    print(f"{d.name}：原片 {start:g} s 到 {end_full if end_full is not None else '结尾'}；字幕 {n_lines} 行、翻译 {n_units} 句；改之前的备份 {bak}")


if __name__ == "__main__":
    main()
