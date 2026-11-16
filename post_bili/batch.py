"""按场次歌单顺序投稿，每首一个稿件，追加到指定合集小节。"""
import argparse
import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workflow.live.paths import Concert, read_json, write_json
from workflow.bili_title import apply_submission_names
from post_bili.receipt import current_receipt


def season(*args):
    if args and args[0] == "list":
        import requests
        from post_bili.upload import bili_cookies
        rows = []
        for page in range(1, 101):
            response = requests.get("https://member.bilibili.com/x2/creative/web/seasons",
                                    cookies=bili_cookies(), params={"pn": page, "ps": 100},
                                    headers={"User-Agent": "adele-workflow/1.0",
                                             "Referer": "https://member.bilibili.com/platform/upload-manager/ep"},
                                    timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                raise ValueError(f"合集查询失败 {result.get('code')} {result.get('message')}")
            data = result["data"]
            rows.extend(data.get("seasons") or [])
            if len(rows) >= data["total"]:
                return json.dumps(rows, ensure_ascii=False)
        raise ValueError("合集列表分页未完成")
    command = [ROOT / "bin/biliup", "-u", ROOT / "post_bili/cookies.json", "season"]
    return subprocess.check_output([*command, *map(str, args)], text=True, cwd=ROOT)


def season_edit(action, payload, retries=3):
    import requests
    from post_bili.upload import bili_cookies
    cookies = bili_cookies()
    response = requests.post("https://member.bilibili.com/x2/creative/web/season/" + action,
                             cookies=cookies, params={"csrf": cookies["bili_jct"]},
                             headers={"User-Agent": "adele-workflow/1.0",
                                      "Referer": "https://member.bilibili.com/platform/upload-manager/ep"},
                             json=payload, timeout=40)
    response.raise_for_status()
    result = response.json()
    if result.get("code") in (256000, 20111) and retries:
        time.sleep(60)
        return season_edit(action, payload, retries - 1)
    if result.get("code") != 0:
        sys.exit(f"合集更新失败 {result.get('code')} {result.get('message')}")


def episodes(args):
    data = json.loads(season("sections", args.season, "--json"))
    sections = data["sections"]
    if args.section:
        sections = [s for s in sections if s["section"]["id"] == args.section]
    else:
        sections = [s for s in sections if s["section"]["title"] == "正片"]
    if len(sections) != 1:
        sys.exit("请用 --section 指定该合集中的一个小节")
    return sections[0]["section"]["id"], sections[0].get("episodes") or []


def upload(song, *flags):
    subprocess.run([sys.executable, ROOT / "post_bili/upload.py", song, *flags],
                   cwd=ROOT, check=True)


def concert_season(concert, song):
    from post_bili.full_library import collection_id, latest_collection
    return collection_id(latest_collection(concert.slug))


def run(args, songs):
    for song in songs:
        if not current_receipt(song):
            upload(song)
    if not args.submit:
        return
    args.season = args.season or concert_season(Concert(args.concert), songs[0])
    data = json.loads(season("sections", args.season, "--json"))
    if data["season"]["no_section"]:
        season_edit("edit", {"season": {**data["season"], "no_section": 0},
                             "sorts": [{"id": s["section"]["id"], "sort": i}
                                       for i, s in enumerate(data["sections"], 1)]})
        if json.loads(season("sections", args.season, "--json"))["season"]["no_section"]:
            sys.exit("B 站尚未启用合集分组")
    section, _ = episodes(args)
    labels = {}
    vids = []
    aids = {}
    for song in songs:
        receipt = song / "post/publish.json"
        pending = song / "post/bili_batch_pending"
        if not current_receipt(song):
            if pending.exists():
                sys.exit(f"{song.name} 上次提交未取得回执，请先核对创作中心")
            pending.touch(exist_ok=False)
            upload(song, "--submit")
        record = read_json(receipt)
        if not (record.get("bvid") or record.get("aid")):
            sys.exit(f"{receipt} 缺少稿件号")
        pending.unlink(missing_ok=True)
        vid = record.get("bvid") or f"av{record['aid']}"
        page_path = song / "post/bili_upload.json"
        page = read_json(page_path)
        apply_submission_names(page, song, read_json(song / "post_draft.json", {}))
        if not page.get("合集显示名称"):
            sys.exit(f"{song.name} 缺少合集显示名称")
        write_json(page_path, page)
        aids[vid] = record.get("aid")
        labels[vid] = page["合集显示名称"]
        vids.append(vid)
    _, before = episodes(args)
    def selected(ep):
        return next((v for v in (ep.get("bvid"), f"av{ep['aid']}") if v in vids), None)
    existing = {selected(e) for e in before}
    missing = [v for v in vids if v not in existing]
    for vid in missing:
        if aids[vid]:
            season_edit("switch", {"season_id": args.season, "section_id": section,
                                   "aid": aids[vid], "title": labels[vid]})
        else:
            print(season("add", section, "--vid", vid))
    _, after = episodes(args)
    for ep in after:
        vid = selected(ep)
        if vid and ep["title"] != labels[vid]:
            season_edit("switch", {"season_id": args.season, "section_id": section,
                                   "aid": ep["aid"], "title": labels[vid]})
    _, after = episodes(args)
    if any(e["title"] != labels[selected(e)] for e in after if selected(e)):
        sys.exit("合集单集名称核对失败")
    ids = {selected(e): e["id"] for e in after}
    if any(v not in ids for v in vids):
        sys.exit("部分稿件尚未出现在小节，可稍后用相同命令继续")
    order = [e["id"] for e in after if not selected(e)] + [ids[v] for v in vids]
    if order != [e["id"] for e in after]:
        print(season("sort", section, *order, "--season-id", args.season))
    if [e["id"] for e in episodes(args)[1]] != order:
        sys.exit("合集顺序核对失败")
    print("合集已核对", *vids)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("concert")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--songs", type=int, nargs="+", help="歌单序号")
    group.add_argument("--all", action="store_true")
    p.add_argument("--season", type=int)
    p.add_argument("--section", type=int)
    p.add_argument("--submit", action="store_true")
    a = p.parse_args()
    concert = Concert(a.concert)
    items = concert.song_items()
    wanted = set(a.songs or [])
    if not items or wanted.difference(it["idx"] for it in items):
        p.error("场次或歌曲序号无效")
    songs = [concert.song_dir(it).resolve() for it in items if a.all or it["idx"] in wanted]
    with (concert.dir / ".bili_batch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run(a, songs)


if __name__ == "__main__":
    main()
