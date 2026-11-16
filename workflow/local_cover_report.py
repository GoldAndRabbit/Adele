"""Build a reference comparison and a resource report for one local MFLUX run."""
import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def single_metric(pattern, log):
    matches = re.findall(pattern, log, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"Expected one measurement for {pattern}, found {len(matches)}")
    return float(matches[0])


def report(output, log_path, *, original=None):
    metadata = json.loads(output.with_suffix(".metadata.json").read_text())
    refs = metadata.get("image_paths") or [metadata["image_path"]]
    log = log_path.read_text()
    stats = {
        "output": str(output),
        "references": refs,
        "generation_seconds": metadata["generation_time_seconds"],
        "elapsed_seconds": single_metric(r"^\s*([\d.]+) real\s", log),
        "peak_process_bytes": int(single_metric(r"^\s*(\d+)\s+peak memory footprint", log)),
        "peak_mlx_gb": single_metric(r"Peak MLX memory:\s*([\d.]+) GB", log),
    }
    if original is not None:
        stats["original"] = str(original)
    with Image.open(output) as rendered, Image.open(original or refs[0]) as primary:
        width, height = rendered.size
        canvas = Image.new("RGB", (width * 2 + 8, height + 54), "#191c22")
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 27)
        draw = ImageDraw.Draw(canvas)
        for i, (image, label) in enumerate([(primary, "原片参考"), (rendered, "生成结果")]):
            fit = ImageOps.contain(image.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
            left = i * (width + 8)
            draw.text((left + 16, 6), label, font=font, fill="white")
            canvas.paste(fit, (left + (width - fit.width) // 2, 54 + (height - fit.height) // 2))
        canvas.save(output.with_suffix(".comparison.jpg"), quality=94)
    output.with_suffix(".run.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("log", type=Path, help="One invocation logged with macOS /usr/bin/time -l")
    args = parser.parse_args()
    report(args.output, args.log)
