"""Finish verification of descriptions corrected after an upload attempt."""
import argparse
import fcntl
import hashlib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workflow.live.paths import read_json, write_json
from post_bili.receipt import current_receipt
from post_bili.edit_description import sync, redacted_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    root = args.folder
    with (root / ".intro-updates.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files = [root / "intro-analysis-review.json", root / "intro-dedup-review.json"]
        paths = {r["path"] for f in files for r in read_json(f, {}).get("records", [])
                 if r.get("needs_online_sync") and r.get("path")}
        results = {}
        for path in sorted(paths):
            directory = Path(path)
            if not current_receipt(directory):
                results[path] = {"status": "not_submitted"}
                continue
            body = read_json(directory / "post/bili_upload.json")["简介"]
            previous = read_json(directory / "post/description_update.json", {})
            if previous.get("status") == "verified" and previous.get("description_sha256") == hashlib.sha256(body.encode()).hexdigest():
                results[path] = {"status": "verified"}
                continue
            try:
                verified = sync(directory, root / "description-before-review")
                results[path] = {"status": "verified" if verified else "pending_verification"}
            except Exception as error:
                results[path] = {"status": "needs_retry", "error": redacted_error(error)[:180]}
            print(directory.name, results[path]["status"], flush=True)
        for file in files:
            if not file.exists():
                continue
            report = read_json(file)
            for row in report["records"]:
                result = results.get(row.get("path"))
                if result:
                    row["online_synced"] = result["status"] == "verified"
                    if result.get("error"):
                        row["online_sync_error"] = result["error"]
                    else:
                        row.pop("online_sync_error", None)
            write_json(file, report)
        summary = dict(Counter(r["status"] for r in results.values()))
        write_json(root / "intro-update-verification-summary.json", {"counts": summary, "results": results})
        print("新增简介核对", summary, flush=True)


if __name__ == "__main__":
    main()
