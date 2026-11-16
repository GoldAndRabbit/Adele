"""Restore proven truncated descriptions from their original submission records."""
import argparse
import fcntl
import sys
import os
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workflow.live.paths import read_json, write_json
from post_bili.edit_description import sync_archive, redacted_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--wait", action="store_true", help="等待当前恢复批次结束后接续核对")
    args = parser.parse_args()
    root = args.plan.parent
    records = root / "description-restoration-online"
    records.mkdir(exist_ok=True)
    with (records / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if args.wait else fcntl.LOCK_NB))
        (root / "description-restoration.pid").write_text(str(os.getpid()))
        jobs = read_json(args.plan)

        def work(job):
            vid = job["bvid"]
            path = records / f"{vid}.json"
            if not job.get("body"):
                return {"bvid": vid, "status": job.get("status", "needs_original_copy")}
            previous = read_json(path, {})
            expected_hash = hashlib.sha256(job["body"].encode()).hexdigest()
            if (previous.get("status") == "preserved_current_description"
                    or (previous.get("status") == "verified"
                        and previous.get("description_sha256") == expected_hash)):
                return previous
            try:
                sync_archive(vid, job["body"], job["receipt"], path,
                             root / "description-restoration-before", only_if_truncated=True)
                result = read_json(path)
            except (Exception, SystemExit) as error:
                result = read_json(path, {"bvid": vid, "status": "needs_retry"})
                result.update(last_error=type(error).__name__, error_message=redacted_error(error)[:180])
                write_json(path, result)
            print(vid, result["status"], result.get("error_message", ""), flush=True)
            return result

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(work, jobs))
        summary = dict(Counter(row["status"] for row in results))
        write_json(root / "description-restoration-summary.json", {"total": len(jobs), "counts": summary})
        print("原始简介恢复核对", summary, flush=True)


if __name__ == "__main__":
    main()
