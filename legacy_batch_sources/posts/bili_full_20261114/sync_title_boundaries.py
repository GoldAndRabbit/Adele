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
from post_bili.upload import bili_cookies, COOKIES
from workflow.live.paths import read_json, write_json

folder = ROOT / "posts/bili_full_20261114"
jobs = read_json(folder / "title-boundary-corrections.json")
plan = read_json(folder / "plan.json")
cookies = bili_cookies()
http = requests.Session()
records = read_json(folder / "title-boundary-online-updates.json", {})


def show(bvid):
    token = read_json(COOKIES)["token_info"]["access_token"]
    for attempt in range(3):
        try:
            response = http.get(
                "https://member.bilibili.com/x/client/archive/view",
                params={"access_key": token, "bvid": bvid}, cookies=cookies,
                headers={"User-Agent": "adele-workflow/1.0",
                         "Referer": "https://member.bilibili.com/"}, timeout=20)
            result = response.json()
            if response.status_code == 200 and result.get("code") == 0:
                return result["data"]
        except (requests.RequestException, ValueError):
            pass
        if attempt < 2:
            time.sleep(3)
    raise RuntimeError(f"{bvid} 平台稿件查询失败")



for row in jobs:
    directory = Path(row["path"])
    receipt = read_json(directory / "post/publish.json")
    if not receipt:
        continue
    page = read_json(directory / "post/bili_upload.json")
    vid = receipt["bvid"]
    if records.get(vid, {}).get("title") == page["标题"]:
        continue
    current = show(vid)
    archive = current["archive"]
    if archive.get("state") == -100:
        print("跳过已删除旧稿", vid, archive.get("reject_reason"), flush=True)
        continue
    before = archive["title"]
    original_cids = [v["cid"] for v in current["videos"]]
    if before != page["标题"]:
        backup = folder / "title-boundary-before"
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
        from post_bili.edit_description import public_description
        complete_desc = public_description(vid)
        if complete_desc is None:
            raise ValueError("完整线上简介尚不可核对，暂不修改标题")
        payload["desc"] = complete_desc
        payload["desc_v2"] = [{"raw_text": complete_desc, "type": 1, "biz_id": ""}]
        for attempt in range(3):
            try:
                response = http.post(
                    "https://member.bilibili.com/x/vu/web/edit",
                    params={"csrf": cookies["bili_jct"]}, cookies=cookies, json=payload,
                    headers={"User-Agent": "adele-workflow/1.0",
                             "Referer": "https://member.bilibili.com/platform/upload/video/frame"},
                    timeout=60)
                response.raise_for_status()
            except requests.RequestException:
                if attempt == 2:
                    raise RuntimeError(f"{vid} 标题修改连接失败，保留进度后重试") from None
                time.sleep(3)
                continue
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
    write_json(folder / "title-boundary-online-updates.json", records)
    write_json(directory / "post/title_boundary_update.json", record)
    print(len(records), vid, page["标题"], record["state"], flush=True)
    if before != page["标题"]:
        time.sleep(1)
print("已投稿标题边界修正全部核对完成", len(records), flush=True)
