"""Publish a reviewed library snapshot and reconcile each batch's collection."""
import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from post_bili import batch
from post_bili.finalize_collection import finalize
from post_bili.upload import bili_cookies, upload_cover, from_page
from post_bili.receipt import current_receipt, video_identity, archive_stale_receipt
from post_bili.edit_description import redacted_error
from workflow.live.paths import Concert, read_json, write_json


def latest_collection(slug):
    response = requests.get(
        f"http://127.0.0.1:8160/api/concerts/{slug}/album_covers", timeout=60)
    response.raise_for_status()
    metadata = response.json()["collection"]
    cover = metadata.get("cover_path")
    if not cover or not metadata.get("cover_url"):
        raise ValueError(f"{slug} 缺少面板中的专用合集封面")
    if not Path(cover).is_file():
        image = requests.get("http://127.0.0.1:8160" + metadata["cover_url"], timeout=60)
        image.raise_for_status()
    if not Path(cover).is_file():
        raise ValueError(f"{slug} 专用合集封面文件不存在")
    return metadata


def collection_id(metadata):
    seasons = json.loads(batch.season("list", "--json"))
    matches = [row for row in seasons if row["season"]["title"] == metadata["title"]]
    if len(matches) > 1:
        raise ValueError("多个同名合集，请核对 " + metadata["title"])
    cover = upload_cover(metadata["cover_path"])
    if matches:
        row = matches[0]
        current = row["season"]
        if (current["cover"].split("/bfs/")[-1] != cover.split("/bfs/")[-1]
                or current.get("desc", "") != metadata["description"]):
            batch.season_edit("edit", {
                "season": {**current, "cover": cover, "desc": metadata["description"]},
                "sorts": [{"id": section["id"], "sort": i}
                          for i, section in enumerate(row["sections"]["sections"], 1)]})
        season_id = current["id"]
    else:
        cookies = bili_cookies()
        response = requests.post(
            "https://member.bilibili.com/x2/creative/web/season/add",
            cookies=cookies, timeout=60,
            headers={"User-Agent": "adele-workflow/1.0",
                     "Referer": "https://member.bilibili.com/platform/upload-manager/ep"},
            data={"title": metadata["title"], "desc": metadata["description"],
                  "cover": cover, "csrf": cookies["bili_jct"], "season_price": 0,
                  "no_section": 0})
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise ValueError(f"创建合集失败 {result}")
        season_id = int(result["data"])
    verified = next(row["season"] for row in json.loads(batch.season("list", "--json"))
                    if row["season"]["id"] == season_id)
    if verified["cover"].split("/bfs/")[-1] != cover.split("/bfs/")[-1]:
        raise ValueError("平台合集封面与专用封面不一致，需继续核对")
    return season_id


def read_platform(command, **kwargs):
    kwargs.setdefault("stderr", subprocess.PIPE)
    return subprocess.check_output(command, **kwargs)


def claimed_bvids(plan=None):
    plan = plan or read_json(ROOT / "posts/bili_full_20261114/plan.json", {"batches": []})
    claimed = {}
    for job in plan["batches"]:
        for row in job["songs"]:
            directory = Path(row["path"])
            receipt = read_json(directory / "post/publish.json", {})
            if receipt.get("bvid"):
                claimed.setdefault(receipt["bvid"], set()).add(str(directory.resolve()))
    return claimed


def reconcile_submission(song, output=None, claimed=None, retired=()):
    """Read the creator's complete archive list before retrying an uncertain submit."""
    page = read_json(song / "post/bili_upload.json")
    claimed = claimed_bvids() if claimed is None else claimed
    pending = read_json(song / "post/bili_batch_pending")
    if not pending or pending.get("video_identity") != video_identity(song):
        raise ValueError(f"{song.name} 缺少本次成片的提交标记，需要核对")
    if output is None:
        output = read_platform(
            [ROOT / "bin/biliup", "-u", ROOT / "post_bili/cookies.json", "list", "-m", "100"],
            cwd=ROOT, text=True, timeout=30)
    normalize = lambda text: re.sub(r"[\s.]+", "", text).casefold()
    aliases = {normalize(page["标题"])}
    history = ROOT / "posts/bili_full_20261114"
    for name in ("title-boundary-corrections.json", "medley-title-corrections.json"):
        for row in read_json(history / name, []):
            if row["song"] == song.name:
                aliases.update(normalize(row[key]) for key in ("before", "after"))
    matches = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) > 1 and re.fullmatch(r"BV[0-9A-Za-z]{10}", fields[0]):
            if normalize(fields[1]) in aliases:
                matches.append(fields[0])
    recent = []
    for bvid in matches:
        if bvid in retired or any(path != str(song.resolve()) for path in claimed.get(bvid, set())):
            continue
        data = json.loads(read_platform(
            [ROOT / "bin/biliup", "-u", ROOT / "post_bili/cookies.json", "show", bvid],
            cwd=ROOT, timeout=20))
        created = data["archive"].get("ctime", 0)
        if created < int(pending["started_at"]):
            continue
        recent.append((bvid, data))
    if len(recent) > 1:
        raise ValueError(f"{song.name} 本次提交期间存在多个同名稿件，需要核对")
    if recent:
        bvid, data = recent[0]
        created = data["archive"]["ctime"]
        if len(data.get("videos", [])) != 1:
            raise ValueError("恢复稿件视频数量不匹配")
        receipt = {**from_page(page), "bvid": bvid, "aid": data["archive"]["aid"],
                   "submitted_at": datetime.now().isoformat(), "recovered_from_platform": True,
                   "video_identity": pending["video_identity"],
                   "recovery_evidence": {"archive_ctime": created,
                                         "attempt_started_at": pending["started_at"]}}
        write_json(song / "post/publish.json", receipt)
        claimed.setdefault(bvid, set()).add(str(song.resolve()))
        print(f"恢复线上投稿回执 {song.name} {bvid}", flush=True)
        return True
    if not re.search(r"^BV[0-9A-Za-z]{10}\t", output, re.M):
        raise ValueError("未获取有效线上稿件列表，保留待核对标记")
    return False


def submit_song(song, line="bda2"):
    """One attempt per sweep; uncertain results never hold up later songs."""
    pending = song / "post/bili_batch_pending"
    if current_receipt(song):
        pending.unlink(missing_ok=True)
        return
    archive_stale_receipt(song)
    if pending.exists():
        raise ValueError(f"{song.name} 上次结果待核对，先继续后续成品")
    write_json(pending, {"started_at": time.time(), "video_identity": video_identity(song)})
    batch.upload(song, "--submit", "--line", line)
    if not current_receipt(song):
        raise ValueError(f"{song.name} 未取得当前成品回执，先继续后续成品")
    pending.unlink(missing_ok=True)


def upload_batch(songs, progress, save, line="bda2"):
    """Keep failures at song scope, including preflight and submission failures."""
    errors = progress.setdefault("song_errors", {})
    for song in songs:
        try:
            if not current_receipt(song):
                if (song / "post/bili_batch_pending").exists():
                    raise ValueError("提交结果待核对，先继续后续成品")
                progress.update(status="uploading", current_song=song.name)
                save()
                batch.upload(song)
                submit_song(song, line=line)
            else:
                (song / "post/bili_batch_pending").unlink(missing_ok=True)
            errors.pop(song.name, None)
        except (Exception, SystemExit) as error:
            errors[song.name] = str(error)
            print(f"单条 {song.name} 待处理，继续下一首：{error}", flush=True)
        save()
    progress.pop("current_song", None)
    missing = [song.name for song in songs if not current_receipt(song)]
    progress["pending_songs"] = missing
    return not missing


def sync_completed_covers(folder, slugs, state, save):
    for slug in slugs:
        progress = state["batches"][slug]
        source_path = folder / f"collection-source-{slug}.json"
        try:
            metadata = latest_collection(slug)
            if read_json(source_path) != metadata:
                collection_id(metadata)
                write_json(source_path, metadata)
            progress.pop("cover_sync_error", None)
        except (Exception, SystemExit) as error:
            progress["cover_sync_error"] = redacted_error(error)
            print(f"{slug} 合集封面同步待恢复 {redacted_error(error)}", flush=True)
            if "-702" in str(error):
                save()
                return
        save()


def reconcile_deferred(plan, state, save):
    deferred = [(job["slug"], Path(s["path"])) for job in plan["batches"]
                for s in job["songs"] if (Path(s["path"]) / "post/bili_batch_pending").exists()]
    if not deferred:
        return
    try:
        output = read_platform(
            [ROOT / "bin/biliup", "-u", ROOT / "post_bili/cookies.json", "list", "-m", "100"],
            cwd=ROOT, text=True, timeout=30)
        claimed = claimed_bvids(plan)
        retired = {r.get("bvid") for job in plan["batches"] for song in job["songs"]
                   for r in song.get("superseded_receipts", []) if r.get("bvid")}
        for slug, song in deferred:
            try:
                pending = song / "post/bili_batch_pending"
                if reconcile_submission(song, output=output, claimed=claimed, retired=retired):
                    pending.unlink(missing_ok=True)
                    state["batches"][slug].get("song_errors", {}).pop(song.name, None)
                elif time.time() - read_json(pending)["started_at"] > 120:
                    pending.unlink()
                    print(f"{song.name} 线上核对未提交，下一轮补投", flush=True)
            except (Exception, SystemExit) as error:
                print(f"{song.name} 仍待核对，保留提交标记：{redacted_error(error)}", flush=True)
    except (Exception, SystemExit) as error:
        print(f"本轮待核对稿件保留标记：{redacted_error(error)}", flush=True)
    save()


def run(plan_path, reconcile_only=False, line="bda2"):
    plan = read_json(plan_path)
    log = plan_path.parent / "progress.json"
    with (ROOT / "post_bili/.full_library.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_json(log, {"batches": {}})
        if reconcile_only:
            reconcile_deferred(plan, state, lambda: write_json(log, state))
            return
        deferred_covers = []
        for job in plan["batches"]:
            slug = job["slug"]
            progress = state["batches"].setdefault(slug, {})
            verified = read_json(plan_path.parent / "collections_verified.json", {}).get(slug)
            if verified:
                progress.update(verified)
                progress.pop("error", None)
            songs = [Path(row["path"]) for row in job["songs"]]
            receipts = [current_receipt(song) for song in songs]
            bound = {s.name: r.get("bvid") or r.get("aid")
                     for s, r in zip(songs, receipts) if r}
            if (progress.get("status") == "complete" and all(receipts)
                    and verified and verified.get("receipt_bvids") == bound):
                # Maintenance for completed batches must not delay fresh uploads.
                deferred_covers.append(slug)
                write_json(log, state)
                continue
            try:
                progress.pop("error", None)
                if not upload_batch(songs, progress, lambda: write_json(log, state), line=line):
                    progress.update(status="needs_attention", error="部分稿件待核对或补投，队列继续后续批次")
                    write_json(log, state)
                    continue
                metadata = latest_collection(slug)
                season = collection_id(metadata)
                write_json(plan_path.parent / f"collection-source-{slug}.json", metadata)
                progress.update(season=season, status="collecting")
                write_json(log, state)
                finalize(plan_path, slug, season)
                progress.update(status="complete", completed_at=datetime.now().isoformat())
            except (Exception, SystemExit) as error:
                progress.update(status="needs_attention", error=str(error))
                print(f"批次 {slug} 待处理 {error}", flush=True)
            write_json(log, state)
        # Reconcile uncertain submits only after fresh uploads have had their
        # opportunity. One shared archive snapshot avoids a full list per song.
        reconcile_deferred(plan, state, lambda: write_json(log, state))
        sync_completed_covers(plan_path.parent, deferred_covers, state, lambda: write_json(log, state))
        print("本轮完成，查看 progress.json 核对合集与异常批次", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--reconcile-only", action="store_true")
    parser.add_argument("--line", default="bda2", help="上传线路；默认 bda2，连接异常时可选其他 biliup 线路")
    args = parser.parse_args()
    run(args.plan.resolve(), reconcile_only=args.reconcile_only, line=args.line)
