"""Prepare a song for portrait review and export an explicitly approved cut."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pysubs2

from workflow.live.package import cover_candidates
from workflow.live.paths import Concert, ROOT, read_json, write_json
from workflow.vertical_preview import render
from workflow.vertical_cover import cover_image, supplement_moments, COVER_STYLE_VERSION


def subtitle(directory):
    for name in ("lyrics_poetic.ass", "lyrics_literal.ass", "lyrics.ass"):
        path = directory / "subs" / name
        if path.is_file():
            return path
    raise ValueError("缺少精校字幕")


def first_lyric(directory):
    events = pysubs2.load(str(subtitle(directory)))
    starts = [e.start for e in events if not e.is_comment and e.style == "Default"
              and e.end > e.start and e.plaintext.strip() and not e.plaintext.lstrip().startswith("《")]
    return min(starts) / 1000 if starts else None


def candidates(concert, item, keep_existing=False, redraw=False):
    if concert.has_cover_pool:
        from workflow.portrait_pool import pool_candidates
        return pool_candidates(concert, item)
    directory = concert.song_dir(item)
    info = read_json(directory / "song.json")
    begin, end = info["slice"]
    folder = directory / "vertical"
    folder.mkdir(exist_ok=True)
    # Prefer moments already ranked in the concert cover-design workflow.
    times = []
    for candidate in cover_candidates(directory):
        t = candidate.get("t")
        if t is not None and begin <= t < end and all(abs(t - other) > 1 for other in times):
            times.append(t)
        if len(times) == 6:
            break
    # Optional manually scouted moments are in concert time, just like ranked frames.
    extra = read_json(concert.dir / "vertical_preview.json", {}).get("cover_moments", {}).get(item["name"], [])
    extra = list(dict.fromkeys(t for t in extra if begin <= t < end))
    times = [t for t in times if all(abs(t - x) > 1 for x in extra)][:max(0, 6-len(extra))] + extra
    existing = read_json(folder / "candidates.json", []) if keep_existing else []
    if existing:
        times = [round(begin + r["time"], 3) for r in existing]
    ranked = [r["t"] for r in cover_candidates(directory) if r.get("t") is not None]
    if len(times) < 18:
        times = supplement_moments(concert, item, begin, end, times, ranked, 18)
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        rows = []
        for index, t in enumerate(times):
            if index < len(existing) and not redraw and existing[index].get("style_version") == COVER_STYLE_VERSION:
                rows.append(existing[index])
                continue
            name = f"cover-{round((t - begin) * 1000)}.jpg"
            path = Path(temp) / name
            cover_image(concert, item, t).save(path, quality=95, subsampling=0)
            # Immutable names ensure a changed candidate invalidates its old selection.
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            name = f"{path.stem}-{digest}.jpg"
            path.replace(folder / name)
            rows.append({"file": name, "time": round(t - begin, 3), "style_version": COVER_STYLE_VERSION})
        manifest = Path(temp) / "candidates.json"
        write_json(manifest, rows)
        manifest.replace(folder / manifest.name)


def prepare(concert, item):
    directory = concert.song_dir(item)
    draft = read_json(directory / "post_draft.json", {})
    if not draft.get("title") or not (draft.get("intro_text") or draft.get("intro")):
        raise ValueError("先完成投稿标题和简介，再进入竖屏审核")
    subtitle(directory)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        if read_json(directory / "song.json", {}).get("preview_mode") == "browser":
            from workflow.vertical_source import prepare as prepare_source
            review = pool.submit(prepare_source, concert, item)
        else:
            review = pool.submit(render, concert, item, False, True)
        covers = pool.submit(candidates, concert, item)
        review.result()
        covers.result()


def revision(directory):
    folder = directory / "vertical"
    full = folder / "full.mp4"
    info = read_json(directory / "song.json", {})
    browser = info.get("preview_mode") == "browser"
    if not browser and not full.exists():
        return None
    files = [subtitle(directory), directory / "post_draft.json", directory / "song.json",
             directory / "watermark.json", folder / "candidates.json", directory / "title_translation.json",
             ROOT / "workflow/portrait_style.json", ROOT / "workflow/portrait_header.py",
             ROOT / "workflow/vertical.py"]
    if browser:
        source = Path(info.get("source_file", ""))
        if not source.is_file():
            return None
        h = hashlib.sha256(str((str(source), source.stat().st_mtime_ns, source.stat().st_size)).encode())
        files.append(ROOT / "workflow/portrait_style.json")
    else:
        h = hashlib.sha256(str((full.stat().st_mtime_ns, full.stat().st_size)).encode())
    for f in files:
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()


def release(directory, cover, expected, lead=0.5, *, concert=None, item=None):
    if lead not in (0.5, 1):
        raise ValueError("首句前保留时长须为 0.5 或 1 秒")
    folder = directory / "vertical"
    with (folder / ".release.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = revision(directory)
        if not expected or expected != current:
            raise ValueError("审核内容已更新，请刷新后重新检查")
        if cover not in [r["file"] for r in read_json(folder / "candidates.json", [])]:
            raise ValueError("请选择当前竖屏候选封面")
        if not (folder / cover).is_file():
            raise ValueError("所选封面文件缺失，请重新生成候选")
        first = first_lyric(directory)
        if first is None:
            raise ValueError("没有有效歌词，无法确定成品起点")
        full = folder / "full.mp4"
        if concert is None:
            slug = directory.parent.parent.name if directory.parent.name == "songs" else directory.parent.name
            concert = Concert(slug) if Concert(slug).info.is_file() else Concert("singles")
        if read_json(directory / "song.json", {}).get("preview_mode") == "browser":
            # A browser review has no burned preview. Render only on an explicit release request.
            render(concert, item or concert.item(directory.name), True, True)
        if subtitle(directory).stat().st_mtime_ns > full.stat().st_mtime_ns:
            raise ValueError("字幕已更新，请先重新生成竖屏审核版")
        start = max(0, first - lead)
        ffmpeg = shutil.which("ffmpeg", path=os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin")
        if not ffmpeg:
            raise ValueError("找不到 ffmpeg")
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            out = Path(tmp) / "release.mp4"
            subprocess.run([ffmpeg, "-v", "error", "-ss", str(start), "-i", str(full),
                            "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "19", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(out)], check=True)
            if revision(directory) != current:
                raise ValueError("生成期间审核内容发生变化，请重新确认")
            token = hashlib.sha256(f"{current}/{cover}/{lead}".encode()).hexdigest()[:16]
            name = f"release-{token}.mp4"
            out.replace(folder / name)
            record = {"file": name, "cover": cover, "lead": lead, "start": start, "revision": current}
            write_json(folder / "release.json", record)
            return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("concert")
    parser.add_argument("song", nargs="?", help="省略时处理整场")
    parser.add_argument("--covers-only", action="store_true", help="只生成封面候选，不启动视频导出")
    parser.add_argument("--prepare-inputs", action="store_true",
                        help="先运行已有演唱会拆分、精校和投稿文案流程，或接入已制作的独立单曲")
    parser.add_argument("--release", action="store_true", help="仅在收到明确指令后生成指定曲目的竖屏成品")
    parser.add_argument("--pre-roll", type=float, choices=(0.5, 1), default=0.5, help="成品首句前保留时长（秒）")
    publish = parser.add_mutually_exclusive_group()
    publish.add_argument("--douyin-preview", action="store_true", help="核对抖音成品、双封面及投稿信息")
    publish.add_argument("--douyin-submit", action="store_true", help="通过 PostFlow 公开投稿指定曲目")
    args = parser.parse_args()
    if args.douyin_preview or args.douyin_submit:
        if not args.song or args.release or args.prepare_inputs or args.covers_only:
            parser.error("抖音投稿需要指定一首已生成成品的曲目，不能同时制作素材")
        from workflow.vertical_publish import run
        concert = Concert(args.concert)
        run(concert, concert.item(args.song), submit=args.douyin_submit)
        return
    if args.release:
        if not args.song or args.covers_only or args.prepare_inputs:
            parser.error("--release 需要指定一首歌，且不能同时准备素材")
        concert = Concert(args.concert)
        directory = concert.song_dir(concert.item(args.song))
        cover = read_json(directory / "vertical/selected.json", {}).get("cover")
        if not cover:
            parser.error("请先在审核页选定竖屏封面")
        print(release(directory, cover, revision(directory), args.pre_roll, concert=concert)["file"])
        return
    if args.covers_only and args.prepare_inputs:
        parser.error("--covers-only 只处理已有原片，不与 --prepare-inputs 同用")
    if args.prepare_inputs:
        if args.concert == "singles":
            from workflow.live.singles import build
            if not args.song:
                parser.error("接入独立单曲需要指定 posts 目录名")
            build([args.song])
        else:
            command = [sys.executable, "-m", "workflow.live", "run", args.concert]
            if args.song:
                command += ["--songs", args.song]
            subprocess.run(command, cwd=ROOT, check=True)

    concert = Concert(args.concert)
    items = [concert.item(args.song)] if args.song else concert.song_items()
    if not items:
        parser.error("场次没有曲目")
    for item in items:
        if args.covers_only:
            candidates(concert, item)
        else:
            prepare(concert, item)
        print("待人工审核", item["name"], flush=True)


if __name__ == "__main__":
    main()
