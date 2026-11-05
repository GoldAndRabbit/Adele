"""独立标题翻译：title_translation.json 为标题译名记录，zh_fixed.__title__ 优先。
单独修订：python -m workflow.song.title_translation posts/NAME --title-zh 中文名 --artist-zh 歌手
"""
import argparse
import json
import re
from pathlib import Path


def display_title(title):
    """Normalize all-lowercase English display names without changing lyrics."""
    return re.sub(r"(^|[\s/\-])([a-z])", lambda m: m[1] + m[2].upper(), title) if title.islower() else title


def load(d):
    p = Path(d) / "title_translation.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save(d, record):
    if record.get("title"):
        record["title"] = display_title(record["title"])
    p = Path(d) / "title_translation.json"
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")


def resolved(d):
    record = load(d)
    p = Path(d) / "zh_fixed.json"
    fixed = json.loads(p.read_text()) if p.exists() else {}
    return str(fixed.get("__title__") or record.get("title_zh") or "").strip().strip("《》")


def apply(d, result):
    draft = Path(d) / "post_draft.json"
    song = (json.loads(draft.read_text()).get("song") or {}) if draft.exists() else {}
    if song.get("artist") and result.get("title") and "》" in result["title"]:
        result["title"] = result["title"].split("》", 1)[0] + "》 " + song["artist"]
    english = load(d).get("title")
    if english and result.get("title"):
        result["title"] = re.sub(r"《[^》]*》", lambda _: f"《{display_title(english)}》", result["title"], count=1)
    zh = resolved(d)
    if not zh:
        return
    old = result.get("title_zh") or ""
    artist = song.get("artist_zh") or load(d).get("artist_zh")
    result["title_zh"] = (f"《{zh}》 {artist}" if artist else
        re.sub(r"《[^》]*》", lambda _: f"《{zh}》", old) if "《" in old else f"《{zh}》 {old}".strip())


def sync(d):
    d = Path(d)
    result = d / "subs/translation/result.json"
    if result.exists():
        data = json.loads(result.read_text())
        apply(d, data)
        result.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        from .song_translation_workflow import build_outputs
        build_outputs(d, d / "subs")
    from workflow.make_meta import build_title
    for p in [d / "post" / f"{d.name}.json", d / "post_draft.json"]:
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        song = data.get("song") or {}
        if not song.get("title"):
            continue
        song["title"] = display_title(song["title"])
        song["title_zh"] = resolved(d)
        song["artist_zh"] = song.get("artist_zh") or load(d).get("artist_zh")
        perf = data.get("performance") or {}
        data["song"] = song
        data["title"] = build_title(song.get("artist_zh"), song.get("artist"), song["title"], song["title_zh"], perf.get("event_zh"), perf.get("event_en"), "中英字幕")
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    # 单曲审核页保存的是投稿信息副本，标题修订时同时刷新。
    root = Path(__file__).resolve().parents[2]
    alias = root / "concerts/singles/songs" / d.name / "post_draft.json"
    post = d / "post" / f"{d.name}.json"
    if alias.exists() and post.exists():
        draft = json.loads(alias.read_text())
        data = json.loads(post.read_text())
        draft.update(title=data["title"], song=data["song"])
        alias.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n")


P_TITLE = """你是资深的中文歌词译者，整首歌词已经翻完，现在定这首歌的中文歌名。
下面有原文歌名、「歌曲理解」、歌词里出现歌名（或歌名关键词）的句子和它们已经定好的中文译法。
- 这首歌在中文世界有材料明确支持的通行译名时优先采用；不得凭记忆宣称官方译名
- 没有通行译名：歌名的中文要和歌词里同一个词的译法一致（歌词里 royals 译成「皇室」，歌名就不要另译成「贵族」）；
  译出这个词在这首歌里的真实含义，不要按字典第一个义项直译（liability 在歌里指「累赘 / 负担」，不是会计上的「负债」）
- 像一个歌名：简短（一般 2～6 个字），不加书名号；人名和角色名使用合适的中文音译或已定译名，不要机械保留英文；缩写或节目编号可保留原文
输出 JSON：{"zh": "中文歌名", "artist_zh": "整行中歌手的中文名", "why": "一句话"}"""


def translate(cache, R, d=None):
    """中文歌名（整首翻完之后）：歌词里出现歌名的句子怎么译的，歌名就跟着；有通行译名用通行译名。
    只改《》里的歌名，中文歌手名不动（R["title_zh"] 形如「《中文歌名》 中文歌手」）。
    定稿表 zh_fixed.json 里有 "__title__"（如「臀部不会说谎」）就直接用它，不问模型（模型每次重跑给的歌名可能不一样）。
    投稿标题（make_meta）也读这里的歌名，两处一致。"""
    from .song_translation_workflow import Cache, cached_ask
    d = Path(d) if d is not None else None
    title, old = R.get("title") or "", R.get("title_zh") or ""
    fixed = (json.loads((d / "zh_fixed.json").read_text()) if d and (d / "zh_fixed.json").exists() else {}).get("__title__")
    record = load(d) if d else {}
    fixed = fixed or record.get("title_zh")
    if fixed:
        zh = fixed.strip().strip("《》")
        R["title_zh"] = re.sub(r"《[^》]*》", f"《{zh}》", old) if "《" in old else f"《{zh}》 {old}".strip()
        R["title_why"] = "定稿表里定的歌名"
        if record.get("artist_zh"):
            R["title_zh"] = f"《{zh}》 {record['artist_zh']}"
        elif not old and "》" in title:
            artist = title.split("》", 1)[1].strip()
            glossary = json.loads(Path(__file__).with_name("glossary.json").read_text())
            artist = glossary.get("names", {}).get(artist, artist)
            R["title_zh"] = f"《{zh}》 {artist}".strip()
            record["artist_zh"] = artist
        if d:
            save(d, {**record, "title_zh": zh, "reason": R["title_why"]})
        return R["title_zh"]
    m = re.search(r"《([^》]*)》", title)
    if not m:
        return old
    name = m.group(1)
    keys = [w for w in re.findall(r"[^\W\d_]{3,}", name.lower())]
    hits = [{"原文": u["orig"], "中文": u.get("v2_final") or u.get("v2", "")} for u in R["units"]
            if u.get("type") != "讲话" and any(k in u["orig"].lower() for k in keys)]
    seen, uniq = set(), []
    for h in hits:
        if h["原文"] not in seen:
            seen.add(h["原文"])
            uniq.append(h)
    brief = R.get("brief") or {}
    payload = json.dumps({"歌名": name, "整行": title, "用户统一用词规则": json.loads(Path(__file__).with_name("glossary.json").read_text()).get("rules", []), "歌曲理解": {k: brief.get(k) for k in ("theme", "voice", "tone", "core_lines")},
                          "歌词里出现歌名的句子": uniq[:12]}, ensure_ascii=False)
    if d:
        cache = Cache(d / "title_translation_cache.json")
    res = cached_ask(cache, "title", P_TITLE, payload, "歌名", check=lambda r: isinstance(r, dict) and str(r.get("zh", "")).strip())
    zh = str(res["zh"]).strip().strip("《》")
    new = re.sub(r"《[^》]*》", f"《{zh}》", old) if "《" in old else f"《{zh}》 {old}".strip()
    artist = str(res.get("artist_zh") or "").strip()
    if artist:
        new = f"《{zh}》 {artist}"
    R["title_zh"], R["title_why"] = new, res.get("why", "")
    if d:
        save(d, {"title": name, "title_zh": zh, "artist_zh": artist, "reason": R["title_why"], "source": "title-stage"})
    return new


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--title-zh")
    parser.add_argument("--artist-zh")
    args = parser.parse_args()
    record = load(args.directory)
    if args.title_zh:
        record.update(title_zh=args.title_zh, source="editor")
        fixed_path = args.directory / "zh_fixed.json"
        fixed = json.loads(fixed_path.read_text()) if fixed_path.exists() else {}
        fixed["__title__"] = args.title_zh
        fixed_path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2) + "\n")
    if args.artist_zh:
        record["artist_zh"] = args.artist_zh
    if not record.get("title_zh"):
        result_path = args.directory / "subs/translation/result.json"
        if not result_path.exists():
            parser.error("自动标题翻译需要已有字幕理解结果；也可传 --title-zh 单独定名")
        from .song_translation_workflow import Cache
        result = json.loads(result_path.read_text())
        translate(Cache(result_path.parent / "title_cache.json"), result, args.directory)
    else:
        save(args.directory, record)
    sync(args.directory)
