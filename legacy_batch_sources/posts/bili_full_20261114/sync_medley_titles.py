"""Sync reviewed medley titles and verify each creator archive."""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from post_bili.upload import bili_cookies
from workflow.live.paths import read_json, write_json

folder = ROOT / "posts/bili_full_20261114"
corrections = {row["song"]: row for row in read_json(folder / "medley-title-corrections.json")}
plan = read_json(folder / "plan.json")
cookies = bili_cookies()
records = read_json(folder / "medley-online-updates.json", {})


def show(bvid):
    for attempt in range(3):
        try:
            return json.loads(subprocess.check_output(
                [ROOT / "bin/biliup", "-u", ROOT / "post_bili/cookies.json", "show", bvid],
                cwd=ROOT, timeout=60))
        except (subprocess.SubprocessError, ValueError):
            if attempt == 2:
                raise
            time.sleep(5)


for batch in plan["batches"]:
    for row in batch["songs"]:
        if row["name"] not in corrections:
            continue
        directory = Path(row["path"])
        receipt = read_json(directory / "post/publish.json")
        if not receipt:
            continue
        page = read_json(directory / "post/bili_upload.json")
        vid = receipt["bvid"]
        current = show(vid)
        archive = current["archive"]
        before = archive["title"]
        original_cids = [v["cid"] for v in current["videos"]]
        if before != page["标题"]:
            backup = folder / "medley-before"
            backup.mkdir(exist_ok=True)
            if not (backup / (vid + ".json")).exists():
                write_json(backup / (vid + ".json"), current)
            keys = ["aid", "copyright", "source", "tid", "desc", "desc_v2",
                    "dynamic", "tag", "interactive", "mission_id", "no_reprint",
                    "is_only_self", "charging_pay", "cover"]
            payload = {k: archive[k] for k in keys if k in archive}
            payload.update(
                title=page["标题"], desc_format_id=9999, csrf=cookies["bili_jct"],
                subtitle={"open": 0, "lan": ""},
                dolby=int(receipt.get("dolby", 1)),
                lossless_music=int(receipt.get("lossless_music", 1)),
                watermark={"state": int(receipt.get("watermark", 0))},
                videos=[{"cid": v["cid"], "filename": v["filename"],
                         "title": v["title"], "desc": v.get("desc", "")} for v in current["videos"]])
            for attempt in range(3):
                response = requests.post(
                    "https://member.bilibili.com/x/vu/web/edit",
                    params={"csrf": cookies["bili_jct"]}, cookies=cookies, json=payload,
                    headers={"User-Agent": "adele-workflow/1.0",
                             "Referer": "https://member.bilibili.com/platform/upload/video/frame"},
                    timeout=60)
                response.raise_for_status()
                result = response.json()
                if result.get("code") == 0:
                    break
                if attempt == 2:
                    raise ValueError(f"{vid} {result}")
                time.sleep(30)
            current = show(vid)
        assert current["archive"]["title"] == page["标题"], f"{vid} 标题未同步"
        assert current["archive"]["cover"] == archive["cover"], f"{vid} 封面地址变化"
        assert [v["cid"] for v in current["videos"]] == original_cids
        record = {"bvid": vid, "title": page["标题"], "state": current["archive"]["state_desc"],
                  "verified_at": datetime.now().isoformat()}
        records[vid] = record
        write_json(folder / "medley-online-updates.json", records)
        write_json(directory / "post/title_update.json", record)
        print(len(records), vid, page["标题"], record["state"], flush=True)
        if before != page["标题"]:
            time.sleep(3)
print("已投稿串烧标题全部核对完成", len(records), flush=True)
