"""Local review bundle only: never selects an AI cover or submits a post."""
from datetime import datetime
import fcntl
from workflow.live.paths import read_json,write_json
from workflow.vertical_post import submission,posting_inputs
from workflow.vertical_post import cover_attachment
from workflow.live.package import cover_candidates
from workflow.live import review
from workflow.posting_cover import active_cover_set, cover_path

def elapsed_seconds(job):
    if job.get("elapsed_seconds") is not None:
        return job["elapsed_seconds"]
    if not job.get("started_at"):
        return None
    end = job.get("finished_at")
    if not end and job.get("status") != "running":
        return None
    start = datetime.fromisoformat(job["started_at"])
    finish = datetime.fromisoformat(end) if end else datetime.now(start.tzinfo)
    return round(max(0, (finish - start).total_seconds()), 3)


def posting_paths(directory):
    """Resolve ready videos and existing platform covers, including previously generated files."""
    result = {platform: {"input_video_path": None, "generated_cover_paths": {}}
              for platform in ("bilibili", "douyin")}
    products = directory / "products"
    manifest = read_json(products / "products.json", {})
    job = read_json(directory / "render_status.json", {})
    for fields in result.values():
        fields.update(render_host=manifest.get("render_host"), production_log=manifest.get("production_log"),
                      current_executor=job.get("executor"), current_render_status=job.get("status"),
                      current_render_log=job.get("log"), elapsed_seconds=elapsed_seconds(job),
                      timing_stages=(manifest.get("timings", []) if job.get("run_id")
                                     and manifest.get("run_id") == job["run_id"] else []),
                      return_seconds=job.get("return_seconds"), checksum_seconds=job.get("checksum_seconds"))
    for row in manifest.get("items", []):
        platform = row.get("platform")
        if platform not in result or row.get("status") != "ready" or not row.get("file"):
            continue
        path = products / row["file"]
        if path.is_file():
            result[platform]["input_video_path"] = str(path.resolve())
    ai = directory / "covers/ai"
    active = {row["file"] for row in read_json(ai / "masters.json", [])}
    for row in read_json(ai / "variants.json", []):
        platform = {"bili": "bilibili", "douyin": "douyin"}.get(row["platform"].split("-")[0])
        path = ai / row["file"]
        if platform and row["master"] in active and path.is_file():
            paths = result[platform]["generated_cover_paths"].setdefault(row["ratio"], [])
            paths.append(cover_path(directory, path, row["platform"].split("-")[0], row["ratio"]))
    return result

def submission_records(concert, item, *, paths=None, entry=None, bili_base=None):
    """Build both platform documents for review, copying, delivery and publication."""
    from argparse import Namespace
    from post_bili.upload import generate

    directory = concert.song_dir(item)
    draft = read_json(directory / "post_draft.json", {})
    paths = paths if paths is not None else posting_paths(directory)
    if entry is None:
        entry = review.load(concert).get("songs", {}).get(item["name"], {})
    bili = bili_base if bili_base is not None else read_json(directory / "post/bili_upload.json")
    if bili is None:
        real = (directory / "post").resolve().parent
        if (directory / "post_draft.json").exists() or (directory / "post" / (directory.name + ".json")).exists():
            bili = generate(directory, Namespace(cover=None, source=None, at=None, tid=None, tid_v2=None, only_self=False))
    bili = dict(bili or {})
    if draft:
        # Keep platform settings, but rebuild content from the canonical draft.
        # A previous export must not pin a placeholder intro or outdated tags.
        from post_bili.upload import description
        fresh = generate(directory, Namespace(cover=None, source=None, at=None, tid=None, tid_v2=None, only_self=False))
        for field in ("标题", "标题字符数", "简介", "标签", "封面16:9", "封面4:3"):
            if field in fresh:
                bili[field] = fresh[field]
        bili["简介"] = description(draft) or fresh.get("简介", "")
    for field, key in (("标题", "title"), ("简介", "intro"), ("标签", "tags")):
        if key in entry:
            bili[field] = entry[key]
    if "简介" in bili:
        bili["简介字符数"] = len(bili["简介"])
    posting_draft, event, artist = posting_inputs(concert, item, draft)
    if "简介" in bili:
        posting_draft["bili_intro"] = bili["简介"]
    dy = submission(posting_draft, event, artist)
    selected = read_json(directory / "vertical/selected.json", {}).get("cover")
    dy.update(paths["douyin"], selected_cover=cover_attachment(directory, selected))
    released = active_cover_set(directory)
    portrait = released.get(("douyin-ai", "3x4"))
    wide = released.get(("douyin-ai", "4x3"))
    if portrait and wide:
        dy["selected_cover"] = {"name": portrait.name, "path": str(portrait), "wide_path": str(wide)}
    if dy["selected_cover"]:
        selected = dict(dy["selected_cover"])
        for key, ratio in (("path", "3x4"), ("wide_path", "4x3")):
            if selected.get(key):
                selected[key] = cover_path(directory, selected[key], "douyin", ratio)
        if selected.get("path"):
            from pathlib import Path
            selected["name"] = Path(selected["path"]).name
        dy["selected_cover"] = selected
    if bili:
        details = dict(paths["bilibili"])
        video = details.pop("input_video_path")
        if video:
            bili["视频文件"] = video
        if entry.get("cover"):
            cover = next((row for row in cover_candidates(directory) if row["id"] == entry["cover"]), None)
            if cover:
                for key, attr in (("封面16:9", "file"), ("封面4:3", "file_4x3")):
                    filename = cover.get(attr)
                    bili[key] = str((directory / filename).resolve()) if filename else None
        for ratio, field in (("16x9", "封面16:9"), ("4x3", "封面4:3")):
            if ("bili-ai", ratio) in released:
                bili[field] = str(released["bili-ai", ratio])
            bili[field] = cover_path(directory, bili.get(field), "bili", ratio)
        from workflow.bili_title import apply_submission_names
        source = read_json(directory / "post" / (item["name"] + ".json"), {}) or {}
        # Singles own their structured title in post/<name>.json; concert
        # songs without that file use post_draft.json, matching load_post().
        title_post = {**draft, **source,
                      "song": {**draft.get("song", {}), **source.get("song", {})},
                      "performance": {**draft.get("performance", {}), **source.get("performance", {})}}
        apply_submission_names(bili, directory, title_post, title_override=entry.get("title"))
        bili["已生成封面路径"] = details.pop("generated_cover_paths")
        bili["制作机器"] = details.pop("render_host")
        bili["制作记录"] = details
        bili["歌手中文昵称"] = dy.get("nicknames_zh", [])
    return {"bilibili": bili, "douyin": dy}


def sync_cover_release(concert, item):
    """Refresh posting exports once the cover manifests have been committed."""
    directory = concert.song_dir(item)
    if (directory / "post_draft.json").is_file() or (directory / "post").is_dir() or (directory / "delivery_bundle.json").exists():
        write_bundle(concert, item)


def write_bundle(concert, item):
    with (concert.song_dir(item) / ".posting.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _write_bundle(concert, item)


def _write_bundle(concert,item):
 d=concert.song_dir(item);products=read_json(d/'products/products.json',{})
 records=submission_records(concert,item)
 ai=d/'covers/ai';masters=read_json(ai/'masters.json',[]);active={m['file'] for m in masters}
 variants=[r for r in read_json(ai/'variants.json',[]) if r['master'] in active]
 failures=[]
 for p in ai.glob('runs/*/candidate-*.json'):
  row=read_json(p,{})
  if row.get('status')=='failed':failures.append({'record':str(p.resolve()),'label':row.get('label'),'reason':row.get('provider_error_code') or row.get('error_type')})
 result={'concert':concert.slug,'song':item['name'],'status':products.get('status'),'videos':[{**r,'path':str((d/'products'/r['file']).resolve())} for r in products.get('items',[])],
  **records,
  'ai_masters':masters,'ai_variants':[{**r,'path':cover_path(d, ai/r['file'], r['platform'].split('-')[0], r['ratio'])} for r in variants],
  'ai_failures':failures,'published':False}
 for target, record in ((d/'post/bili_upload.json', records['bilibili']),
                        (d/'vertical/douyin_submission.json', records['douyin']),
                        (d/'delivery_bundle.json', result)):
  if record and read_json(target) != record:
   target.parent.mkdir(exist_ok=True)
   write_json(target, record)
 return result
