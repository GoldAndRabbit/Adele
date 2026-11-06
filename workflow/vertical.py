"""Wrap a finished landscape performance in a 1080×1920 portrait frame."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pysubs2
from PIL import Image

from workflow.portrait_header import draw_portrait_header, STYLE, PINGFANG
from workflow.artist_credit import artist_credit
from workflow.subtitle_spelling import display_english


def write_lower_captions(source, destination, start):
    captions = pysubs2.load(str(source))
    captions.info.update(PlayResX="1080", PlayResY="1920", WrapStyle="0")
    style = pysubs2.SSAStyle(
        fontname=STYLE["english_font"], fontsize=STYLE["english_size"], alignment=8,
        primarycolor=pysubs2.Color(255, 255, 255),
        marginv=STYLE["subtitle_y"], marginl=72, marginr=72, outline=STYLE["subtitle_outline"], shadow=0,
    )
    translation_color = "{\\fn" + STYLE["chinese_font"] + "\\fs" + str(STYLE["chinese_size"]) + r"\c&HFFFFFF&}"
    captions.styles = {"Default": style}
    offset = sum(float(part) * 60 ** i for i, part in enumerate(reversed(start.split(":"))))
    captions.shift(ms=-round(offset * 1000))
    # The portrait header already carries the song title. Editorial notes belong in the review table.
    captions.events = [
        event for event in captions
        if not event.is_comment and event.style != "Note" and event.end > max(0, event.start)
        and not (event.plaintext.startswith("《") and "AI 自动字幕" in event.plaintext)
    ]
    for event in captions:
        event.start = max(0, event.start)
        lines = event.plaintext.splitlines()
        if lines:
            translated = [line.strip(" ♪♫♬🎵🎶") for line in lines[1:]]
            rows = [translation_color + line for line in translated if line]
            rows.append(r"{\r}" + display_english(lines[0].strip()))
            event.text = r"\N".join(rows)
        event.style = "Default"
        event.marginl = event.marginr = event.marginv = 0
    captions.save(str(destination))


def watermark_graph(args, source_label):
    """Brand the clear performance frame only, using the horizontal player's song clock."""

    directory = args.song_directory or args.source.parent
    plan_path = directory / "watermark.json"
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else {}
    logo = Path(__file__).resolve().parents[1] / plan.get("logo", "assets/adele-logo.png")
    start = sum(float(v) * 60 ** i for i, v in enumerate(reversed((args.caption_start or args.start).split(":"))))
    items = [item for item in plan.get("items", []) if not args.cover_frame
             and item["t"] + item["dur"] > start and not (args.duration and item["t"] >= start + args.duration)]
    if not items:
        return "", source_label, []
    if len(items) > 1:
        outputs = "".join(f"[floatinglogo{i}]" for i in range(1, len(items) + 1))
        graph = f"[2:v]split={len(items)}{outputs};"
    else:
        graph = "[2:v]null[floatinglogo1];"
    last = source_label
    for i, item in enumerate(items, 1):
        t, duration, fade = item["t"], item["dur"], item["fade"]
        if t + duration <= start or (args.duration and t >= start + args.duration):
            continue
        width = round(1080 * plan["width"])
        graph += (f"[floatinglogo{i}]scale={width}:-1,format=rgba,colorchannelmixer=aa={plan['opacity']},"
                  f"setpts=PTS+{start}/TB,fade=in:st={t}:d={fade}:alpha=1,"
                  f"fade=out:st={t+duration-fade}:d={fade}:alpha=1,setpts=PTS-STARTPTS[mark{i}];"
                  f"[{last}][mark{i}]overlay=x=W*{item['x']}:y=H*{item['y']}:shortest=1:"
                  f"enable='between(t,{t-start},{t+duration-start})'[brand{i}];")
        last = f"brand{i}"
    inputs = ["-loop", "1", "-framerate", str(args.fps), "-i", str(logo)] if graph else []
    return graph, last, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--zh", required=True)
    parser.add_argument("--en", required=True)
    parser.add_argument("--song")
    parser.add_argument("--song-zh", help="已确认的中文歌名，显示在标题第二行")
    parser.add_argument("--intro", help="One short sentence about the performance")
    parser.add_argument("--cover-frame", action="store_true", help="Extract one still from the clean portrait composition")
    parser.add_argument("--captions", type=Path, help="Subtitle file timed to the clean input video")
    parser.add_argument("--background", choices=["solid", "blur", "bright-blur"], default="blur")
    parser.add_argument("--palette", choices=["gold-event"], default="gold-event", help=argparse.SUPPRESS)
    parser.add_argument("--start", default="0")
    parser.add_argument("--fps", type=int, choices=(25, 30, 50, 60), default=30)
    parser.add_argument("--output-width", type=int, choices=(720, 1080), default=1080)
    parser.add_argument("--song-directory", type=Path, help="Song metadata for a separately prepared video input")
    parser.add_argument("--caption-start", help="Start on the song-relative subtitle timeline")
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    args.zh = artist_credit(args.zh)
    args.en = artist_credit(args.en)
    blurred = args.background != "solid"
    canvas = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0) if blurred else "#181518")
    crop = ""
    # Source posts record their active picture as normalized coordinates.
    box_path = (args.song_directory or args.source.parent) / "content_box.json"
    if (args.source.name == "source.mp4" or args.song_directory) and box_path.exists():
        box = json.loads(box_path.read_text())
        if box["w"] < 1 and box["h"] == 1:
            # Restore the original frame dimensions after removing the pillarboxing.
            crop = f"crop=iw*{box['w']}:ih:iw*{box['x']}:0,scale=iw/{box['w']}:ih,"
    graph = (
        f"[0:v]fps={args.fps},{crop}scale=1080:1920:force_original_aspect_ratio=decrease:"
        "force_divisible_by=2,setsar=1[clip];"
    )
    mark_inputs = []
    if blurred:
        graph += "[clip]split=3[center][upper][lower];"
        # Clean footage can use the bottom edge. Finished clips may have burned-in lyrics there.
        lower_y = "ih-oh" if args.captions or args.cover_frame else "ih*0.28"
        for label, height, y, sigma in [("upper", "ih/2", "0", 12), ("lower", "ih*0.30", lower_y, 28)]:
            graph += (
                f"[{label}]crop=iw:{height}:0:{y},scale=270:240:"
                f"force_original_aspect_ratio=increase,crop=270:240,gblur=sigma={sigma},"
                f"scale=1080:960,setsar=1[{label}bg];"
            )
        marks, center, mark_inputs = watermark_graph(args, "center")
        graph += marks
        if STYLE.get("portrait_soft_lower_edge"):
            graph += (f"[{center}]format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                      "a='255*min(1,max(0,(H-Y)/56))'[softcenter];")
            center = "softcenter"
        graph += (
            f"[upperbg][lowerbg]vstack[bg];[bg][{center}]overlay=(W-w)/2:(H-h)/2[base];"
            "[base][1:v]overlay=shortest=1[v]"
        )
    else:
        marks, center, mark_inputs = watermark_graph(args, "clip")
        graph += marks
        graph += f"[1:v][{center}]overlay=(W-w)/2:(H-h)/2:eof_action=endall[v]"
    directory = args.song_directory or args.source.parent
    translation = args.song_zh
    if not translation:
        from workflow.live.paths import read_json
        translation = read_json(directory / "title_translation.json", {}).get("title_zh") or read_json(directory / "post_draft.json", {}).get("song", {}).get("title_zh")
    if args.song and not translation:
        raise ValueError("缺少已确认的中文歌名，请先运行标题翻译步骤")
    draw_portrait_header(canvas, args.song, args.en, args.zh, args.intro, blurred, song_zh=translation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.png"
        canvas.save(frame)
        title_input = ["-loop", "1", "-framerate", str(args.fps), "-i", str(frame)]
        if args.captions:
            subtitle_path = Path(tmp) / "lower.ass"
            write_lower_captions(args.captions, subtitle_path, args.caption_start or args.start)
            font_directory = f":fontsdir='{PINGFANG.parent}'" if PINGFANG else ""
            graph += f";[v]ass=filename='{subtitle_path}'{font_directory}[captioned]"
        output_label = "[captioned]" if args.captions else "[v]"
        if args.output_width != 1080:
            graph += f";{output_label}scale={args.output_width}:-2[output]"
            output_label = "[output]"
        # The launchd review server does not inherit the interactive Homebrew PATH.
        search_path = os.pathsep.join((os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"))
        ffmpeg = shutil.which("ffmpeg", path=search_path)
        if not ffmpeg:
            raise FileNotFoundError("找不到 ffmpeg")
        if args.cover_frame:
            subprocess.run([ffmpeg, "-v", "error", "-n", "-ss", args.start, "-i", str(args.source),
                            *title_input, *mark_inputs, "-filter_complex", graph, "-map", output_label,
                            "-frames:v", "1", "-q:v", "2", str(args.output)], check=True)
            return
        subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-n",
            "-ss", args.start, "-i", str(args.source), *title_input, *mark_inputs,
            "-filter_complex", graph,
            "-map", output_label, "-map", "0:a:0?", *(["-t", str(args.duration)] if args.duration else []),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-ac", "2", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(args.output),
        ], check=True)


if __name__ == "__main__":
    main()
