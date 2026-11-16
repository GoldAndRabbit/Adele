"""Build the review and publishing ledger from actual local outputs."""
import csv
from collections import Counter
from pathlib import Path

from workflow.live.paths import CONCERTS, Concert, read_json
from workflow.portrait_validation import preview_problem
from workflow.vertical_cover import header_labels, original_source, COVER_STYLE_VERSION
from workflow.vertical_post import cover_attachment
from workflow.vertical_workflow import revision
from workflow.live.cover_pool import frames

base = Path(__file__).resolve().parent
repairs = read_json(base / "header-repairs.json")
rows = []
for group in sorted(CONCERTS.iterdir()):
    if not group.is_dir():
        continue
    concert = Concert(group.name)
    pool_count = len(frames(concert)) if concert.has_cover_pool else 0
    for item in concert.song_items():
        if item.get("review_hidden"):
            continue
        name = item["name"]
        directory = concert.song_dir(item)
        folder = directory / "vertical"
        key = group.name + "--" + name
        report = read_json(base.parent / "browser-library/status" / (key + ".json"), {})
        manifest = read_json(folder / "candidates.json", [])
        covers = {r["file"] for r in manifest}
        full = folder / "full.mp4"
        info = read_json(directory / "song.json", {})
        browser = info.get("preview_mode") == "browser" and (folder / "original-selected.mp4").is_file()
        captions = any((directory / "subs" / n).is_file() for n in ("lyrics_poetic.ass", "lyrics_literal.ass", "lyrics.ass"))
        cover_ready = (pool_count >= 100 if concert.has_cover_pool else len(covers) == 18) and all((folder / f).is_file() for f in covers)
        style_ready = all(r.get("style_version") == COVER_STYLE_VERSION or r.get("layout", {}).get("version") == COVER_STYLE_VERSION for r in manifest)
        ready = browser and captions and cover_ready and style_ready and (folder / "douyin_submission.json").is_file()
        if ready:
            stage = "合格"
        elif report.get("status") == "running":
            stage = "制作中"
        elif report.get("status") == "failed":
            stage = "需重试"
        else:
            try:
                original_source(concert, item)
                stage = "排队" if captions else "待补精校"
            except FileNotFoundError:
                stage = "待原片"
        selected = read_json(folder / "selected.json", {}).get("cover")
        pair = cover_attachment(directory, selected) if selected in covers else None
        release = read_json(folder / "release.json", {})
        final = bool(release.get("file") and (folder / release["file"]).is_file()
                     and release.get("cover") == selected and release.get("revision") == revision(directory))
        receipt = read_json(folder / "douyin-receipt.json", {})
        rows.append([group.name, name, item["title"], stage, pool_count if concert.has_cover_pool else len(covers), bool(pair and pair.get("wide_path")),
                     final, receipt.get("status", "待投稿"), f"http://127.0.0.1:8160/#/{group.name}/{name}"])
output = base / "全库制作投稿进度.csv"
temp = output.with_suffix(".tmp")
with temp.open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["场次", "目录", "曲目", "竖屏预览", "候选封面数", "已选双封面", "当前成片", "抖音回执", "精校页"])
    writer.writerows(rows)
temp.replace(output)
print(len(rows), Counter(r[3] for r in rows), "双封面",sum(r[5] for r in rows), "成片",sum(r[6] for r in rows),Counter(r[7] for r in rows))
