"""Prepare a concert frame locally and optionally paint it with FIBO 2 Edit Turbo."""
import argparse
from datetime import datetime
import sys
import json
import os
import socket
from pathlib import Path
import subprocess
import time

import cv2
import numpy as np

if __package__:
    from .local_cover_report import report
else:
    from local_cover_report import report

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "assets/cover-logo-templates/live-7-hd-768.png"
CLEAN_VERSION = "live7-parts-v3"
PROMPT_VERSION = "concert-oil-v2"


def concert_prompt(scene_note="", opaque_helmets=False):
    """Combine the house oil-paint treatment with observations of this exact frame."""
    if opaque_helmets:
        return ("An oil painting after this exact performance still. " + scene_note.strip() +
                " Both visors are entirely opaque polished metal and smoked mirror glass. "
                "Render the front plates as uninterrupted smooth reflections of the amber lights. "
                "Keep their actual shapes and poses. Full-bleed unlettered painting.")
    parts = [
        "Paint this exact concert frame as a luminous full-bleed oil painting. "
        "Match the camera angle, actual stage colors, lighting and number of visible performers.",
        scene_note.strip(),
        "Keep facial likeness, gaze, eyelids, expression and hand positions faithful to the frame. "
        "Retain visible eyewear only when it appears in the reference. Keep bare eyes free of frames and lenses. "
        "Leave blurred backgrounds and empty stage areas indistinct. Respect occluded details and the shapes of microphones and instruments. "
        "Use restrained brushwork on faces and broader strokes on the stage. "
        "Fill the canvas edge to edge. Leave all lettering, broadcast graphics and badges out of the artwork.",
    ]
    return " ".join(part for part in parts if part)


def detail(gray):
    gray = gray.astype(np.float32)
    return gray - cv2.GaussianBlur(gray, (0, 0), 2)


def locate_logo(frame):
    h, w = frame.shape[:2]
    # Compare at the broadcast reference width, convert the accepted mask back to native pixels.
    height = round(h * 768 / w)
    corner = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (768, height))
    x0 = 768 * 2 // 3
    search = corner[:max(1, height // 3), x0:]
    template = cv2.imread(str(TEMPLATE), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise FileNotFoundError(TEMPLATE)
    th, tw = template.shape
    if search.shape[0] < th:
        return None, {"matched": False, "score": None}
    scores = cv2.matchTemplate(detail(search), detail(template), cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    # Strong lighting edges between LIVE, 7 and HD can depress the whole-box score.
    # Verify each glyph group independently at the same candidate location.
    patch = search[y:y+th, x:x+tw]
    parts = []
    for ys, xs in [(slice(0,15),slice(0,29)), (slice(0,33),slice(31,62)), (slice(33,48),slice(30,62))]:
        score_map = cv2.matchTemplate(detail(patch[ys, xs]), detail(template[ys, xs]), cv2.TM_CCOEFF_NORMED)
        parts.append(round(float(score_map[0,0]), 4))
    matched = score >= .80 or (score >= .55 and min(parts) >= .75)
    info = {"matched": matched, "score": round(score, 4), "glyph_scores": parts}
    if not matched:
        return None, info
    x += x0
    _, glyphs = cv2.threshold(template, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = np.zeros_like(corner)
    mask[y:y + th, x:x + tw] = glyphs
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    info["mask_bbox_xywh"] = cv2.boundingRect(mask)
    return mask, info


def clean(frame, *, expect_live7=False):
    mask, info = locate_logo(frame)
    if mask is None:
        if expect_live7 or (info["score"] or 0) >= .55:
            raise ValueError(f"转播台标待核对，暂停生图：{info}")
        return frame, info
    cleaned = cv2.inpaint(frame, mask, max(2, round(4 * frame.shape[1] / 768)), cv2.INPAINT_NS)
    _, residual = locate_logo(cleaned)
    info["after_score"] = residual["score"]
    if residual["matched"] or (residual["score"] or 0) >= .55:
        raise ValueError(f"修补后仍疑似存在转播台标，暂停生图：{residual}")
    return cleaned, info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("directory", type=Path, help="New run directory")
    parser.add_argument("--model", type=Path, help="Local FIBO weights; omit for preprocessing only")
    prompts = parser.add_mutually_exclusive_group()
    prompts.add_argument("--prompt", help="Complete prompt override")
    prompts.add_argument("--scene-note", default="", help="Details observed in the selected frame")
    parser.add_argument("--expect-live7", action="store_true")
    parser.add_argument("--opaque-helmets", action="store_true")
    parser.add_argument("--logo-ellipse", nargs=4, type=float, metavar=("CX", "CY", "RX", "RY"),
                        help="Reviewed watermark center and radii as fractions of the frame")
    parser.add_argument("--logo-box", nargs=4, type=float, action="append", default=[], metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--trim-lower-band", type=float, default=0, help="Reviewed bottom broadcast graphics band, fraction of frame height")
    parser.add_argument("--reference-width", type=int, help="Cap reference width before inference")
    parser.add_argument("--generator", default=str(ROOT / "work/local-flux3/venv/bin/mflux-generate-fibo2-edit"))
    parser.add_argument("--preview-song", nargs=2, metavar=("CONCERT", "SONG"))
    parser.add_argument("--source-time", type=float, help="Reference time in the original broadcast, in seconds")
    parser.add_argument("--worker-config", type=Path, help="Run inference on a configured Mac worker")
    parser.add_argument("--face-reference", type=Path, help="Exact same-frame face crop for identity conditioning")
    parser.add_argument("--reference-max-area", type=int, choices=[262144,524288,1048576],
                        help="Conditioning image pixel budget for multi-reference inference")
    args = parser.parse_args()
    if args.preview_song and (not args.model or args.source_time is None):
        parser.error("--preview-song requires --model and --source-time")
    start = time.monotonic()
    frame = cv2.imread(str(args.reference))
    if frame is None:
        parser.error(f"Unreadable reference: {args.reference}")
    args.directory.mkdir(parents=True, exist_ok=False)
    output = args.directory / "master.png"
    reference = args.directory / "reference.png"
    cleaned, info = clean(frame, expect_live7=args.expect_live7)
    info["cleanup_version"] = CLEAN_VERSION
    if args.logo_ellipse:
        h, w = cleaned.shape[:2]
        cx, cy, rx, ry = args.logo_ellipse
        if not (0 < rx <= cx <= 1-rx and 0 < ry <= cy <= 1-ry):
            parser.error("Logo ellipse must fit inside the frame")
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.ellipse(mask, (round(cx*w), round(cy*h)), (round(rx*w), round(ry*h)), 0, 0, 360, 255, -1)
        cleaned = cv2.inpaint(cleaned, mask, max(3, round(w/200)), cv2.INPAINT_NS)
        info["reviewed_logo_ellipse"] = args.logo_ellipse
    if args.logo_box:
        h, w = cleaned.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        for left, top, right, bottom in args.logo_box:
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                parser.error("Logo box must fit inside the reference")
            mask[round(top*h):round(bottom*h), round(left*w):round(right*w)] = 255
        cleaned = cv2.inpaint(cleaned, mask, max(3, round(w/200)), cv2.INPAINT_NS)
        info["reviewed_logo_boxes"] = args.logo_box
    if args.trim_lower_band:
        if not 0 < args.trim_lower_band < .25:
            parser.error("Lower broadcast band must occupy less than a quarter of the frame")
        h, w = cleaned.shape[:2]
        kept = 1 - args.trim_lower_band
        left = round(w * (1 - kept) / 2)
        cleaned = cleaned[:round(h * kept), left:left + round(w * kept)]
        info["trim_lower_band"] = args.trim_lower_band
    # Discard symmetric encoded black bars only when both bands are uniformly black.
    rows = cleaned.max(axis=2).mean(axis=1)
    active = np.flatnonzero(rows > 5)
    if len(active):
        top, bottom = int(active[0]), len(rows) - 1 - int(active[-1])
        if .025 * len(rows) < min(top, bottom) and abs(top - bottom) < .015 * len(rows):
            cleaned = cleaned[top:len(rows)-bottom]
            info["black_bars_top_bottom"] = [top, bottom]
    if args.reference_width and cleaned.shape[1] > args.reference_width:
        scale = args.reference_width / cleaned.shape[1]
        cleaned = cv2.resize(cleaned, (args.reference_width, round(cleaned.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    if not cv2.imwrite(str(reference), cleaned):
        raise OSError(reference)
    info.update(prompt_template=None if args.prompt else PROMPT_VERSION, scene_note=args.scene_note, source=str(args.reference.resolve()), template=TEMPLATE.name,
                preprocessing_seconds=round(time.monotonic() - start, 3))
    (args.directory / "preprocess.json").write_text(json.dumps(info, indent=2) + "\n")
    if args.model:
        log = args.directory / "generate.log"
        generator = [args.generator]
        local_generator = ROOT / "work/local-flux3/venv/bin/mflux-generate-fibo2-edit"
        if Path(args.generator) == local_generator:
            generator = [str(local_generator.with_name('python')),
                         str(ROOT / 'workflow/local_fibo_generate.py')]
        inputs = [str(reference.resolve())]
        if args.face_reference:
            inputs.append(str(args.face_reference.resolve()))
        command = ["/usr/bin/time", "-l", *generator, "--model", str(args.model),
                   "--base-model", "fibo2-edit-turbo", "--image-paths", *inputs,
                   "--prompt", args.prompt or concert_prompt(args.scene_note, args.opaque_helmets), "--width", "1024", "--height", "576", "--steps", "4",
                   "--guidance", "1", "--seed", "42", "--metadata", "--output", str(output)]
        env = dict(os.environ, HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                   MLX_MAX_OPS_PER_BUFFER="4", MLX_MAX_MB_PER_BUFFER="16")
        if args.reference_max_area:
            env['FIBO_REFERENCE_AREA'] = str(args.reference_max_area)
        started = datetime.now().astimezone().isoformat()
        if args.worker_config:
            from workflow.remote_fibo import run_inference
            run_inference(args.worker_config, command[command.index('--model'):], reference, output, log,
                          reference_area=args.reference_max_area)
        else:
            with log.open("w") as stream:
                subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
        metadata_path = output.with_suffix('.metadata.json')
        metadata = json.loads(metadata_path.read_text())
        metadata.setdefault('executor', socket.gethostname())
        metadata.setdefault('quantization_bits', metadata.get('quantize'))
        if args.face_reference:
            metadata['identity_reference'] = str(args.face_reference.resolve())
            metadata['reference_max_area'] = args.reference_max_area or 1048576
            metadata['conditioning_profile'] = 'composition-detail-v1' if args.reference_max_area else 'trained-multireference'
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
        timing = dict(started_at=started, finished_at=datetime.now().astimezone().isoformat(),
                      mlx_max_ops_per_buffer=int(env["MLX_MAX_OPS_PER_BUFFER"]),
                      mlx_max_mb_per_buffer=int(env["MLX_MAX_MB_PER_BUFFER"]))
        (args.directory / "task-time.json").write_text(json.dumps(timing, indent=2) + "\n")
        report(output, log, original=args.reference.resolve())
        if args.preview_song:
            subprocess.run([sys.executable, "-m", "workflow.fibo_previews", *args.preview_song,
                            str(args.directory.resolve()), "--source-time", str(args.source_time)],
                           cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
