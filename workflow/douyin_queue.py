"""Upload all prepared batches continuously and queue collections separately."""
import argparse
import asyncio
import fcntl
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from workflow.live.paths import ROOT, read_json, write_json
from workflow.vertical_publish import DailyPostingLimit, PublicationPending, TransientPublishError, publish


QUEUE = ROOT / "work/douyin-full"


def error_summary(error):
    # Playwright request call logs can include authentication headers and signed
    # media URLs. Only persist the cause, never the raw request diagnostics.
    lines = str(error).splitlines()
    message = lines[0] if lines else type(error).__name__
    return re.sub(r"https?://\S+", "[URL]", message)


async def publish_with_retries(plan, receipt, context):
    attempt = 0
    while True:
        attempt += 1
        try:
            await publish(plan, receipt, check_existing=False)
            return True
        except DailyPostingLimit as error:
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=30, second=0, microsecond=0)
            write_json(QUEUE / "status.json", dict(context, status="daily_limit", error=str(error),
                       stopped_at=now.isoformat(), resume_after=tomorrow.isoformat()))
            print("DAILY_LIMIT", context["batch"], context["song"], str(error), flush=True)
            return False
        except Exception as error:
            message = error_summary(error)
            transient = isinstance(error, (PlaywrightTimeout, TimeoutError, ConnectionError,
                                           PublicationPending, TransientPublishError))
            if isinstance(error, PlaywrightError):
                transient = transient or any(token in message.lower() for token in (
                    "net::err_", "target closed", "target page, context or browser has been closed",
                    "browser has disconnected", "connection closed", "crashed", "socket hang up",
                    "econnreset", "econnrefused", "econnaborted", "etimedout", "eai_again", "enotfound"))
            print("ERROR", context["batch"], context["song"], attempt, message, flush=True)
            if not transient:
                write_json(QUEUE / "status.json", dict(context, status="needs_attention", error=message))
                raise RuntimeError(message) from None
            delay = min(15 * (2 ** min(attempt - 1, 5)), 300)
            write_json(QUEUE / "status.json", dict(context, status="retrying", attempt=attempt,
                       error=message, retry_after_seconds=delay))
            print("RETRY", context["batch"], context["song"], "IN", delay, flush=True)
            await asyncio.sleep(delay)
            write_json(QUEUE / "status.json", dict(context, status="uploading", attempt=attempt + 1))


def plan_for(row):
    directory = Path(row["directory"])
    meta = read_json(directory / "delivery_bundle.json")["douyin"]
    cover = meta["selected_cover"]
    video = Path(meta["input_video_path"])
    for path in (video, Path(cover["path"]), Path(cover["wide_path"])):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not meta.get("title") or len(meta["title"].encode("utf-16-le")) > 60:
        raise ValueError(f"投稿标题无效：{row['name']}")
    if not meta.get("description") or len(meta["description"].encode("utf-16-le")) > 2000:
        raise ValueError(f"作品描述无效：{row['name']}")
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(video),
    ]))
    return dict(meta, track=row["title"], duration=duration, video=str(video),
                portrait=cover["path"], landscape=cover["wide_path"],
                account=os.environ.get("DOUYIN_ACCOUNT", "goldandrabbit"))


def enqueue_collection(batch):
    # This explicitly requested Douyin queue is independent of the default
    # platform policy used when rendering new videos.
    slug = batch["slug"]
    if slug in read_json(QUEUE / "collections.json", {}):
        return
    pending = read_json(QUEUE / "pending_collections.json", {})
    pending[slug] = dict(status="pending", total=len(batch["songs"]))
    write_json(QUEUE / "pending_collections.json", pending)


async def next_batch():
    state = read_json(QUEUE / "status.json", {})
    if state.get("status") == "daily_limit":
        resume_after = datetime.fromisoformat(state["resume_after"])
        if resume_after.tzinfo is None:
            raise ValueError("每日投稿限制的恢复时间缺少时区")
        if datetime.now(timezone.utc) < resume_after:
            print("DAILY_LIMIT", state["resume_after"], state.get("error", ""), flush=True)
            return
    batches = read_json(QUEUE / "inventory.json")
    for batch in batches:
        rows = batch["songs"]
        remaining = [row for row in rows if read_json(
            Path(row["directory"]) / "vertical/douyin-receipt.json", {}
        ).get("status") != "confirmed"]
        if not remaining:
            if any(not row["posted"] for row in rows):
                enqueue_collection(batch)
            continue
        slug = batch["slug"]
        for row in remaining:
            directory = Path(row["directory"])
            receipt = directory / "vertical/douyin-receipt.json"
            write_json(QUEUE / "status.json", dict(status="uploading", batch=slug,
                       song=row["name"], total=len(rows)))
            print("START", slug, row["name"], flush=True)
            plan = plan_for(row)
            with (directory / "vertical/.douyin.lock").open("a") as song_lock:
                fcntl.flock(song_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not await publish_with_retries(plan, receipt,
                        dict(batch=slug, song=row["name"], total=len(rows))):
                    return
            print("DONE", slug, row["name"], flush=True)
        enqueue_collection(batch)
        print("BATCH_UPLOADED", slug, "COLLECTION_QUEUED", flush=True)
    write_json(QUEUE / "status.json", dict(status="uploads_complete"))
    print("UPLOADS_COMPLETE", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-lock", action="store_true", help="接续正在运行的旧版上传队列")
    args = parser.parse_args()
    QUEUE.mkdir(parents=True, exist_ok=True)
    with (QUEUE / "queue.lock").open("a") as queue_lock:
        flags = fcntl.LOCK_EX if args.wait_lock else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(queue_lock, flags)
        asyncio.run(next_batch())
