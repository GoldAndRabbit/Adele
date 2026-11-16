"""Song-local FIBO source reference sheets; no sidebar or production queue."""
from pathlib import Path
import subprocess
import tempfile
from PIL import Image, ImageDraw
from workflow.live.paths import ROOT, read_json, write_json
from workflow.templates import COVER_SIZES as SIZES
BASE = ROOT / 'work/fibo-batch'

def sample(concert, item, policy=None):
    """Extract a dozen original stills from this track's confirmed source range."""
    folder = BASE / concert.slug / "selection" / item["name"]
    folder.mkdir(parents=True, exist_ok=True)
    if policy is None:
        policy = read_json(concert.dir / "vertical_source.json")["songs"][item["name"]]
    spec = read_json(concert.dir / "fibo-cover-plan.json", {}).get(item["name"], {})
    source = Path(spec.get("source") or policy["source"])
    start, end = policy["slice"]
    clip = Path(policy["directory"]) / "source.mp4"
    marker = dict(source=str(source), mtime=source.stat().st_mtime_ns, slice=policy["slice"])
    from workflow.browser_library import source_identity
    decoder = policy.get("audio_decoder") or read_json(concert.info, {}).get("audio_decoder")
    use_clip = clip.is_file() and read_json(clip.parent / "source.json") == source_identity(source, policy["slice"], decoder)
    if end <= start:
        raise ValueError("Invalid song range")
    if read_json(folder / "source.json") == marker and (folder / "frames.jpg").is_file():
        return
    cells = []
    sheet = Image.new("RGB", (720, 360), "#18191e")
    draw = ImageDraw.Draw(sheet)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        for j in range(12):
            offset = (end-start) * (.10 + .80*j/11)
            at = round(start + offset, 3)
            frame = Path(tmp) / f"{j:02d}.jpg"
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(round(offset,3) if use_clip else at),
                            "-i", str(clip if use_clip else source), "-frames:v", "1", "-vf", "scale=1280:-2",
                            "-q:v", "2", str(frame)], check=True, capture_output=True, timeout=90)
            with Image.open(frame) as im:
                im.thumbnail((179, 99))
                x, y = j%4*180, j//4*120
                sheet.paste(im, (x,y))
                draw.text((x,y+99), str(j), fill="white")
            cells.append((str(folder/frame.name), at))
        sheet.save(Path(tmp)/"frames.jpg")
        for p in Path(tmp).iterdir():
            p.replace(folder/p.name)
    write_json(folder/"times.json", cells)
    write_json(folder/"source.json", marker)
