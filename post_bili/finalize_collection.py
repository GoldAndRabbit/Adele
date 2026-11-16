"""Finalize an uploaded batch using the creator collection API."""
import argparse
import fcntl
import json
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from post_bili.batch import season, season_edit
from post_bili.upload import bili_cookies
from post_bili.receipt import current_receipt
from workflow.live.paths import read_json, write_json


def section_state(section_id):
    response = requests.get(
        "https://member.bilibili.com/x2/creative/web/season/section",
        params={"id": section_id}, cookies=bili_cookies(),
        headers={"User-Agent": "adele-workflow/1.0", "Referer": "https://member.bilibili.com/"},
        timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0 or result["data"]["section"]["id"] != section_id:
        raise ValueError("小节查询失败")
    return result["data"]


def grouped_season(season_id):
    row = next(r for r in json.loads(season("list", "--json")) if r["season"]["id"] == season_id)
    if row["season"]["no_section"]:
        season_edit("edit", {
            "season": {**row["season"], "no_section": 0},
            "sorts": [{"id": section["id"], "sort": i}
                      for i, section in enumerate(row["sections"]["sections"], 1)],
        })
        row = next(r for r in json.loads(season("list", "--json")) if r["season"]["id"] == season_id)
        if row["season"]["no_section"]:
            raise ValueError("B站尚未启用合集分组，稍后自动重试")
    return row


def finalize(plan_path, slug, season_id):
    plan = read_json(plan_path)
    job = next(b for b in plan["batches"] if b["slug"] == slug)
    row = grouped_season(season_id)
    section = next(s for s in row["sections"]["sections"] if s["title"] == "正片")
    section_id = section["id"]

    def episode(song):
        directory = Path(song["path"])
        receipt = current_receipt(directory)
        if not receipt:
            raise ValueError(f"{song['name']} 缺少当前成品版本的投稿回执")
        page = read_json(directory / "post/bili_upload.json")
        response = requests.get(
            "https://api.bilibili.com/x/web-interface/view", params={"bvid": receipt["bvid"]},
            cookies=bili_cookies(),
            headers={"User-Agent": "adele-workflow/1.0", "Referer": "https://www.bilibili.com/"},
            timeout=30)
        response.raise_for_status()
        result = response.json()
        aid = receipt.get("aid")
        if result.get("code") in (-404, 62002):
            private = json.loads(subprocess.check_output(
                [ROOT / "bin/biliup", "-u", ROOT / "post_bili/cookies.json",
                 "show", receipt["bvid"]], cwd=ROOT, timeout=60, stderr=subprocess.PIPE))
            if (aid and private["archive"]["aid"] != aid) or len(private["videos"]) != 1:
                raise ValueError(f"{song['name']} 稿件信息不匹配")
            archive = private["archive"]
            if archive.get("state") == -100:
                issue_path = plan_path.parent / "archive_issues"
                issue_path.mkdir(exist_ok=True)
                write_json(issue_path / (receipt["bvid"] + ".json"),
                           {"slug": slug, "song": song["name"], "bvid": receipt["bvid"],
                            "state": archive.get("state_desc"), "reason": archive.get("reject_reason")})
                raise ValueError(f"{song['name']} 旧稿已被平台下架，需要处理")
            aid = private["archive"]["aid"]
            cid = private["videos"][0]["cid"]
        elif result.get("code") == 0:
            aid = result["data"]["aid"]
            cid = result["data"]["cid"]
        else:
            raise ValueError(f"{song['name']} 稿件查询失败 {result.get('code')}")
        title = page["合集显示名称"]
        if len(title) > 80:
            canonical = read_json(directory / "post" / f"{directory.name}.json", {}).get("song", {})
            short = " ".join(filter(None, [canonical.get("title"), canonical.get("title_zh")]))
            if canonical.get("title") and short and len(short) <= 80:
                title = short
            else:
                song_info = read_json(directory / "post_draft.json", {}).get("song", {})
                translation = read_json(directory / "title_translation.json", {})
                english = (song_info.get("title") or "").split(" / ")
                chinese = (translation.get("title_zh") or song_info.get("title_zh") or "").split(" / ")
                for count in (2, 1):
                    title = " / ".join(english[:count]) + " " + " / ".join(chinese[:count]) + "（串烧）"
                    if len(title) <= 80:
                        break
            if len(title) > 80:
                raise ValueError(f"{song['name']} 合集名称超过平台 80 字限制")
            page["合集显示名称"] = title
            write_json(directory / "post/bili_upload.json", page)
            bundle_path = directory / "delivery_bundle.json"
            bundle = read_json(bundle_path)
            if bundle and isinstance(bundle.get("bilibili"), dict):
                bundle["bilibili"]["合集显示名称"] = title
                write_json(bundle_path, bundle)
        return {"aid": aid, "cid": cid, "title": title,
                "previous_season": (result.get("data") or {}).get("season_id")}

    with ThreadPoolExecutor(max_workers=3) as pool:
        desired = list(pool.map(episode, job["songs"]))
    if len({e["aid"] for e in desired}) != len(desired):
        raise ValueError("多个成片复用了同一回执，请先核对并补投缺失成片")
    for episode in desired:
        previous = episode.pop("previous_season", None)
        if previous and previous != season_id:
            season_edit("switch", {"season_id": season_id, "section_id": section_id,
                                   "aid": episode["aid"], "title": episode["title"]})
    before = section_state(section_id)["episodes"] or []
    # Old versions must not remain in a collection verified for this batch.
    superseded = [r for song in job["songs"] for r in song.get("superseded_receipts", [])]
    old_aids = {r.get("aid") for r in superseded if r.get("aid")}
    old_bvids = {r.get("bvid") for r in superseded if r.get("bvid")}
    current_aids = {e["aid"] for e in desired}
    for ep in before:
        if (ep["aid"] in old_aids or ep.get("bvid") in old_bvids) and ep["aid"] not in current_aids:
            season("remove", ep["id"])
    before = section_state(section_id)["episodes"] or []
    if any((e["aid"] in old_aids or e.get("bvid") in old_bvids)
           and e["aid"] not in current_aids for e in before):
        raise ValueError("旧成片尚未从本次合集移出")
    existing = {e["aid"]: e for e in before}
    missing = [e for e in desired if e["aid"] not in existing]
    if missing:
        season_edit("section/episodes/add", {"sectionId": section_id, "episodes": missing})
    for ep in desired:
        if ep["aid"] in existing and existing[ep["aid"]]["title"] != ep["title"]:
            season_edit("switch", {"season_id": season_id, "section_id": section_id,
                                   "aid": ep["aid"], "title": ep["title"]})
    after = section_state(section_id)["episodes"]
    by_aid = {e["aid"]: e for e in after}
    ids = [by_aid[e["aid"]]["id"] for e in desired]
    extras = [e["id"] for e in after if e["aid"] not in {r["aid"] for r in desired}]
    order = extras + ids
    if order != [e["id"] for e in after]:
        season_edit("section/edit", {"section": {"id": section_id, "seasonId": season_id,
                                                "title": "正片", "type": 1},
                                    "sorts": [{"id": eid, "sort": i} for i, eid in enumerate(order, 1)]})
    final = section_state(section_id)["episodes"]
    assert [e["id"] for e in final] == order, "小节顺序核对失败"
    assert all(by_aid[e["aid"]]["title"] == e["title"] for e in desired), "小节名称核对失败"
    path = plan_path.parent / "collections_verified.json"
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = read_json(path, {})
        records[slug] = {"season": season_id, "section": section_id,
                         "episodes": len(desired), "status": "complete",
                         "receipt_bvids": {Path(s["path"]).name: current_receipt(Path(s["path"])).get("bvid")
                                           for s in job["songs"]}}
        write_json(path, records)
    print(f"{slug} 合集已核对 {len(desired)} 集", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("slug")
    parser.add_argument("season", type=int)
    args = parser.parse_args()
    try:
        finalize(args.plan, args.slug, args.season)
    except (Exception, SystemExit) as error:
        from post_bili.edit_description import redacted_error
        print(redacted_error(error), file=sys.stderr)
        sys.exit(1)
