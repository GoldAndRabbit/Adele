"""Bind publication receipts to the rendered video, independently of its title."""
import hashlib
from pathlib import Path

from workflow.live.paths import read_json

ROOT = Path(__file__).resolve().parents[1]


def resolved_video(value):
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def video_identity(song, video=None):
    song = Path(song)
    page = read_json(song / "post/bili_upload.json", {})
    path = resolved_video(video or page["视频文件"])
    manifest = read_json(song / "products/products.json", {})
    ready = [r for r in manifest.get("items", [])
             if r.get("platform") == "bilibili" and r.get("status") == "ready"]
    if ready:
        if len(ready) != 1 or (song / "products" / ready[0]["file"]).resolve() != path:
            raise ValueError(f"{song.name} 投稿文件与当前成品版本不一致")
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "run_id": manifest.get("run_id"),
            "sha256": ready[0].get("sha256") if ready else None}


def receipt_matches(song, receipt):
    if not receipt or not (receipt.get("bvid") or receipt.get("aid")):
        return False
    current = video_identity(song)
    recorded = receipt.get("video_identity")
    if recorded:
        return recorded == current
    # Older receipts can be migrated only when their actual video path matches.
    # A title-based recovery fabricated the path from today's page; it needs
    # independent creation-time evidence before it can be trusted.
    if receipt.get("recovered_from_platform") and not receipt.get("recovery_evidence"):
        return False
    return bool(receipt.get("video") and resolved_video(receipt["video"]) == Path(current["path"]))


def current_receipt(song):
    receipt = read_json(Path(song) / "post/publish.json", {})
    return receipt if receipt_matches(song, receipt) else None


def archive_stale_receipt(song):
    path = Path(song) / "post/publish.json"
    if not path.exists() or current_receipt(song):
        return
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    history = path.parent / "publish-history"
    history.mkdir(exist_ok=True)
    target = history / f"stale-{digest}.json"
    if target.exists() and target.read_bytes() != path.read_bytes():
        raise ValueError("历史投稿回执备份冲突")
    path.replace(target)
