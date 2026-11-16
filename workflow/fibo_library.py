"""Prepare song-local reference sheets or render the reviewed visible sidebar queue."""
import argparse
import fcntl
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen
from urllib.parse import quote
import json

from PIL import Image, ImageDraw

from workflow.delivery_bundle import sync_cover_release
from workflow.cover_brand import BRAND_LAYOUT
from workflow.cover_eye_review import check_for_blink
from workflow.ai_cover import credit_layout_version, render_variants, reviewed_revision
from workflow.fibo_concert import check_group_reference, generate_one
from workflow.live.paths import ROOT, Concert, read_json, write_json

BASE = ROOT / "work/fibo-batch"
SIZES = {("bili-ai", "16x9"): (1920, 1080), ("bili-ai", "4x3"): (1440, 1080),
         ("douyin-ai", "3x4"): (1080, 1440), ("douyin-ai", "4x3"): (1440, 1080)}


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


def verify_ui(url, slug, song, master):
    with urlopen(f"{url}/api/concerts/{quote(slug)}/songs/{quote(song)}/cover_design", timeout=45) as resp:
        data = json.load(resp)
    variants = [v for v in data["variants"] if v["master"] == master]
    if len(variants) != 4 or {(v["platform"], v["ratio"]) for v in variants} != SIZES.keys():
        raise ValueError("Expected four published platform variants")
    for v in variants:
        with urlopen(url+v["url"], timeout=30) as resp, Image.open(io.BytesIO(resp.read())) as im:
            if im.size != SIZES[v["platform"],v["ratio"]]:
                raise ValueError(f"Incorrect dimensions for {v['file']}")
            im.verify()


def current_previews(c, item):
    directory = c.song_dir(item) / "covers/ai"
    approved = reviewed_revision(directory)
    if approved:
        return all(r.get("brand_layout") == BRAND_LAYOUT for r in approved[1])
    masters = read_json(directory / "masters.json", [])
    spec = read_json(c.dir / "fibo-cover-plan.json", {}).get(item["name"])
    local = next((m["file"] for m in masters if m.get("provider") == "local" and spec
                  and m.get("source_time") == spec["source_time"] and (directory / m["file"]).is_file()), None)
    rows = [v for v in read_json(directory / "variants.json", []) if v["master"] == local]
    return (len(rows) == 4 and {(r["platform"], r["ratio"]) for r in rows} == SIZES.keys()
            and all(r.get("brand_layout") == BRAND_LAYOUT and r.get("credit_layout") == credit_layout_version(r["ratio"]) and (directory / r["file"]).is_file()
                    for r in rows))


def render(c, item, model, url, display_slug):
    ai = c.song_dir(item) / "covers/ai"
    approved = reviewed_revision(ai)
    if approved:
        verify_ui(url, display_slug, item["name"], approved[0]["file"])
        return "verified"
    base = BASE / c.slug
    rows = read_json(base/"results.json", [])
    previous = next((r for r in rows if r["song"] == item["name"]), None)
    masters = [m for m in read_json(ai/"masters.json", []) if m.get("provider") == "local" and (ai / m["file"]).is_file()]
    spec = read_json(c.dir / "fibo-cover-plan.json", {}).get(item["name"])
    if not spec:
        return "awaiting_reference"
    policy = read_json(c.dir / "vertical_source.json", {}).get("songs", {}).get(item["name"])
    if policy:
        start, end = policy["slice"]
    else:
        segments = read_json(c.dir / "segments.json", {}).get("items", [])
        segment = next((s for s in segments if s.get("name") == item["name"]), None)
        if (not segment or spec.get("source") != read_json(c.info).get("source_file")
                or spec.get("source_range") != [segment["start"], segment["end"]]):
            raise ValueError("Reference has no matching song interval")
        start, end = spec["source_range"]
    if not start <= spec["source_time"] < end:
        raise ValueError("Reference outside this song's confirmed interval")
    check_group_reference(item, spec, (ai / spec["reference"]).read_bytes())
    match = next((m for m in masters if m.get("source_time") == spec["source_time"]), None)
    if match:
        check_for_blink(ai / spec["reference"], spec, "reference")
        check_for_blink(ai / match["file"], spec, "master")
        render_variants(c, item, ai / match["file"], match["label"], compact=True)
        master = match["file"]
    else:
        result = generate_one(c,item,spec,base,model)
        master = "master-" + hashlib.sha256((Path(result["run"])/"master.png").read_bytes()).hexdigest()[:12] + ".png"
        if previous:
            rows[rows.index(previous)] = result
        else:
            rows.append(result)
        write_json(base/"results.json",rows)
        if result.get("status") == "awaiting_visual_review":
            return "awaiting_visual_review"
    verify_ui(url,display_slug,item["name"],master)
    retired = {m["file"] for m in masters if m.get("source_time") != spec["source_time"]}
    if retired:
        for manifest, key in [("masters.json", "file"), ("variants.json", "master")]:
            records = read_json(ai / manifest, [])
            pending = ai / (manifest + ".next")
            write_json(pending, [r for r in records if r[key] not in retired])
            pending.replace(ai / manifest)
        sync_cover_release(c, item)
    return "verified"


def run(args):
    with urlopen(args.url+"/api/concerts",timeout=90) as resp:
        sidebar=json.load(resp)
    for slug in args.include_concert:
        concert = Concert(slug)
        group = next(g for g in sidebar if g["slug"] == slug)
        visible = {row["name"] for row in group["tracks"]}
        group["tracks"].extend({"name": item["name"]} for item in concert.song_items() if item["name"] not in visible)
    BASE.mkdir(parents=True,exist_ok=True)
    write_json(BASE/"sidebar.json",sidebar)
    if args.action=="render" and not (args.model and (args.model/"model_index.json").is_file()):
        raise ValueError("Provide staged FIBO weights")
    with (BASE/f"sidebar-{args.action}.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for group in sidebar:
            slug=group["slug"]
            if args.group and slug!=args.group:
                continue
            c=Concert("singles" if slug.startswith("artist_") or slug=="super_bowl_halftime" else slug)
            status_path=BASE/c.slug/f"sidebar-{args.action}.json"
            status_path.parent.mkdir(parents=True,exist_ok=True)
            status=read_json(status_path,{})
            for track in group["tracks"]:
                name=track["name"]
                if (BASE/"PAUSED").exists():
                    return
                try:
                    item=c.item(name)
                    if args.action=="sample":
                        sample(c,item)
                        result="sampled"
                    elif status.get(name) == "verified" and current_previews(c, item):
                        continue
                    else:
                        result=render(c,item,args.model,args.url,slug)
                except (Exception,SystemExit) as exc:
                    result=f"error: {exc}"
                status[name]=result
                write_json(status_path,status)
                print(slug,name,result,flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=["sample","render"])
    p.add_argument("--group")
    p.add_argument("--include-concert", action="append", default=[], help="Include every song in a newly imported concert")
    p.add_argument("--url",default="http://127.0.0.1:8160")
    p.add_argument("--model",type=Path)
    run(p.parse_args())
