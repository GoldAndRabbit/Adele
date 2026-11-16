# -*- coding: utf-8 -*-
"""Canonical posting drafts and cover text/candidate compatibility helpers.

Metadata generation is called by live.stages.posting. AI image production and
release belong to workflow.covers; this module never owns a batch or model queue.
"""

import json
import re
from pathlib import Path

from .paths import ROOT, read_json, write_json

LANG_ZH = {"es": "西班牙语", "en": "英语", "it": "意大利语", "ja": "日语", "pt": "葡萄牙语", "fr": "法语"}
COVER_RE = re.compile(r"^(closeup|half|full|scene|pool|cover)_(\d\d)\.jpg$")   # pool：从整场封面池排的（cover_pool.py）
FRAME_RE = re.compile(r"^frame_(?:(closeup|half|full|scene|pool)_)?(\d\d)_([\d.]+)s\.jpg$")


def save_picked(c, it, cid):
    """选定的候选封面（cid）存成 PNG 放进这首成品所在的 post/：post/<歌>_cover_picked_<日时分>.png 和 _4x3_ 那张；
    审核页「下载」、封面池随机分配都用。单曲的 covers 在 <歌>/post/cover，顺着软链接找。返回存下的路径。"""
    import time
    from PIL import Image
    covers = (c.song_dir(it) / "covers").resolve()
    base = covers.parent.parent if covers.parent.name in ("exp", "post") else covers.parent
    post = base / "post"
    post.mkdir(exist_ok=True)
    stamp = time.strftime("%d%H%M")
    saved = []
    for src, suffix in ((covers / f"{cid}.jpg", ""), (covers / f"{cid}_4x3.jpg", "_4x3")):
        if src.exists():
            dst = post / f"{it['name']}_cover_picked{suffix}_{stamp}.png"
            Image.open(src).convert("RGB").save(dst)
            saved.append(str(dst.relative_to(ROOT)))
    return saved


def cover_candidates(d):
    """covers/ 下的候选：[{id, file, file_4x3, t}]，t 是在整场里的时间（秒）。"""
    cdir = d / "covers"
    if not cdir.exists():
        return []
    reconstructed = read_json(cdir / "reconstructed.json", {}) or {}
    times = {}
    for f in cdir.iterdir():
        m = FRAME_RE.match(f.name)
        if m:
            times[f"{m[1] or 'cover'}_{m[2]}"] = float(m[3])
    out = []
    for f in sorted(cdir.iterdir()):
        m = COVER_RE.match(f.name)
        if m:
            cid = f"{m[1]}_{m[2]}"
            f43 = cdir / f"{cid}_4x3.jpg"
            out.append({"id": cid, "file": f"covers/{f.name}", "file_4x3": f"covers/{f43.name}" if f43.exists() else None,
                        "t": times.get(cid), "reconstructed": cid in reconstructed})
    order = {"closeup": 0, "half": 1, "full": 2, "cover": 3}   # 特写、半身、全身，按清晰度补的放最后
    out.sort(key=lambda x: (order.get(x["id"].split("_")[0], 9), x["id"]))
    # 排过序（cover_rank.py 的 rank.json）就按名次排：前三是算法推荐，审核页单独一组
    ranked = {x["id"]: x for x in (read_json(cdir / "rank.json", {}) or {}).get("items", [])}
    if ranked:
        for x in out:
            r = ranked.get(x["id"])
            if r:
                x.update(rank=r["rank"], score=r["score"], why=r.get("why"), eyes=r.get("eyes"))
        out.sort(key=lambda x: x.get("rank") or 999)
    return out


def subtitle_line(c, it):
    info = read_json(c.info)
    song = read_json(c.song_dir(it) / "song.json", {})
    if song.get("cover_subtitle"):
        return song["cover_subtitle"]
    langs = song.get("langs") or [song.get("lang", "en")]
    cast = read_json(c.song_dir(it) / "post_draft.json", {}).get("song") or {}
    zh = info.get("title_artist_zh") or cast.get("artist_zh") or info.get("artist_zh")
    en = info.get("title_artist_en") or cast.get("artist") or info.get("artist", "")
    if (en.casefold() == info.get("artist", "").casefold() and info.get("artist_zh")
            and not re.search(r"[\u3400-\u9fff]", zh or "")):
        zh = info["artist_zh"]
    # 明确的封面定稿优先；默认同时保留中英文艺名。
    who = song.get("cover_artist") or info.get("cover_artist") or " ".join(dict.fromkeys(x for x in (zh, en) if x))
    # 同台合唱的嘉宾（song.json guests）写在歌手后面：夏奇拉 × 杜阿·利帕（用户 2026-10-26：不能只写夏奇拉）
    who = " × ".join([who] + [g.get("zh") or g["name"] for g in song.get("guests") or []])
    # 第二行带演唱会简称（title_short，没有就用中文名）：洛德 Lorde · ACL音乐节2026 · 中英字幕
    event = info.get("title_short") or concert_names(info)[0]
    if not who or not event:
        raise ValueError("封面缺少歌手或演出简称，请先补齐投稿资料")
    return " · ".join(x for x in (who, event, f"中{''.join(LANG_ZH.get(x, '外')[0] for x in langs)}字幕") if x)


def concert_names(info):
    """演唱会中文名 / 英文名，都去掉歌手名。英文名优先用 title_en（正式名太长时的简称，如 ACL Festival 2026）。"""
    zh, en = info.get("artist_zh") or info["artist"], info["artist"]
    c_zh = (info.get("title_zh") or "").replace(zh, "", 1).strip()
    c_en = re.sub(rf"^{re.escape(en)}\s+", "", info.get("title_en") or info.get("title") or "").strip()
    return c_zh, c_en


def cover_title(c, it):
    return read_json(c.song_dir(it) / "song.json", {}).get("cover_title") or it["title"]


def compact_cover_title(c, item):
    title = cover_title(c, item)
    parts = [part.strip() for part in title.split(" / ")]
    if len(parts) >= 3 or (len(parts) > 1 and len(item["title"].split(" / ")) >= 3):
        return parts[0] + "等串烧"
    return title




def song_title_zh(c, it):
    """歌名的中文译名：翻译流程的歌名步骤（subs result.json 的 title_zh），没有再看字幕片头的 __title__ 缓存；
    和原文一样（TQG / Dai Dai）就没有。"""
    from workflow.song.title_translation import resolved
    chosen = resolved(c.song_dir(it))
    if chosen:
        return chosen if chosen.lower() != it["title"].lower() else ""
    res = read_json(c.song_dir(it) / "subs" / "translation" / "result.json", {}) or {}
    cache = read_json(c.song_dir(it) / "zh_cache.json", {}) or {}
    zh = res.get("title_zh") or next((v for k, v in cache.items() if k.startswith("__title__::")), "")
    m = re.match(r"\s*《(.+?)》", zh or "")
    t = m.group(1).strip() if m else ""
    return "" if not t or t.lower() == it["title"].lower() else t


def post_title(c, it, cast=None):
    from workflow.bili_title import for_post
    info = read_json(c.info)
    directory = c.song_dir(it)
    if cast is None:
        post = (read_json(directory / 'post' / (it['name'] + '.json'), {})
                or read_json(directory / 'post_draft.json', {}))
    else:
        post = {'song': cast}
    song = post.get('song') or {}
    post = {**post, 'song': {**song, 'title': song.get('title') or song.get('title_song') or it['title'],
                            'artist': song.get('artist') or it.get('artist') or info.get('artist')},
            'performance': post.get('performance') or {'event_zh': info.get('title_zh') or info.get('title'),
                                                       'event_en': info.get('title_en'), 'date': info.get('date')}}
    return for_post(directory, post)


def draft_meta(c, it, seg, a):
    d = c.song_dir(it)
    dst = d / "post_draft.json"
    from post_bili.upload import description
    existing = read_json(dst, {})
    from workflow.templates import valid_tags
    complete = (all((existing.get("intro") or {}).get(k) for k in ("song", "performance", "lyrics"))
                and 1800 <= len(description(existing)) <= 2000
                )
    if dst.exists() and not a.force and complete:
        draft = existing
        if not valid_tags(draft.get("tags")):
            from workflow.make_meta import generate_tags
            draft["tags"] = generate_tags(json.dumps({"song": draft.get("song"), "performance": draft.get("performance")}, ensure_ascii=False), draft.get("tags", []))
            write_json(dst, draft)
        if draft.get("title") != post_title(c, it) or draft.get("intro_text") != description(draft):
            draft["title"] = post_title(c, it)
            draft["intro_text"] = description(draft)
            write_json(dst, draft)
        return
    from workflow import make_meta
    info = read_json(c.info)
    song = read_json(d / "song.json", {})
    lang = "、".join(LANG_ZH.get(x, "原文") for x in (song.get("langs") or [song.get("lang", "en")]))
    songs = c.song_items()
    pos = next(i for i, x in enumerate(songs, 1) if x["name"] == it["name"])
    facts = {
        "演唱会": info.get("title"), "艺人": info.get("artist"), "巡演": info.get("tour"),
        "日期": info.get("date"), "场馆": info.get("venue"), "城市": info.get("city"),
        "本场第几首": f"{pos} / {len(songs)}", "歌名": it["title"],
        "原唱 / 合作": it.get("artist"), "歌单备注（setlist.fm）": it.get("notes") or "无",
        "片段时长（秒）": round(seg["end"] - seg["start"]),
        "转播": info.get("broadcast"),
        "Genius 歌曲信息（发行日期、原唱、合作艺人）": [x for x in song.get("genius", []) if x],
    }
    user = ("原视频信息（整场演唱会中的一首，以下是全部可用事实）：\n" + json.dumps(facts, ensure_ascii=False, indent=2)
            + f"\n\n字幕：{lang} + 中文（标签写作“中{''.join(x[0] for x in lang.split('、'))}字幕”）"
            + "\n\n补充说明：歌单备注里的英文请转述成中文，不要照抄。"
            + "\n\n介绍篇幅（覆盖上面的字数要求）：intro_song 和 intro_performance 各写约 550 字，intro_lyrics 写约 800 字，三部分合并含空行1800–2000字符，内容要充实："
            + "intro_song 写这首歌的创作 / 发行背景、原唱与合作、风格和主题、成绩与影响；"
            + "intro_performance 写这场演唱会（巡演、场馆、城市、转播）、这首歌在本场的位置和前后衔接、"
            + "歌单备注里的现场改编或嘉宾，以及这首歌的演出风格、舞台上特别的地方和主唱造型（按「现场画面观察」写）；"
            + "intro_lyrics 按要求详细讲歌词。只写材料里有的事实和广为人知的常识，不编数字和日期；"
            + "这站是巡演的第几站、是不是最后一站，这首是不是安可，材料里没有就不要写（「本场第几首」只说第几首）。")
    if existing and not (d / "post_draft.before_standard_meta.json").exists():
        write_json(d / "post_draft.before_standard_meta.json", existing)
    video, begin, finish = c.source, seg["start"], seg["end"]
    clip = d / "vertical/original-selected.mp4"
    if clip.is_file():
        video, begin, finish = clip, 0, seg["end"] - seg["start"]
    elif not video.is_file() and song.get("source_file"):
        video = Path(song["source_file"])
    notes = make_meta.stage_notes(video, begin, finish, d / "stage_notes.json")
    user += make_meta.media_material(notes, make_meta.lyrics_material(d / "lyrics.txt", d / "zh_cache.json"))
    gen = make_meta.generate_intro(user, label=f"元数据 {it['title']}")
    if not valid_tags(gen.get("tags")):
        gen["tags"] = make_meta.generate_tags(user, gen.get("tags", []))
    from workflow.bili_title import posting_artist
    artist_zh, artist_en = posting_artist(
        {"artist": gen.get("artist_en"), "artist_zh": gen.get("artist_zh")}, info)
    write_json(dst, {
        "title": post_title(c, it, {"artist": artist_en, "artist_zh": artist_zh}),
        "song": {"title": gen.get("song_title") or it["title"], "artist": artist_en,
                 "artist_zh": artist_zh, "release_year": gen.get("release_year")},
        "performance": {"event": gen.get("event") or info.get("title"), "date": gen.get("event_date") or info.get("date")},
        "intro": {"song": gen.get("intro_song"), "performance": gen.get("intro_performance"), "lyrics": gen.get("intro_lyrics")},
        "intro_text": make_meta.intro_text(gen),
        "tags": gen.get("tags", []),
        "subtitles": lang.split("、") + ["中文"],
    })


def validate_presentation(c, it):
    """完成标记前核验实际投稿资料，不能用生成成功代替格式合格。"""
    info = read_json(c.info)
    draft = read_json(c.song_dir(it) / "post_draft.json", {})
    title = draft.get("title") or ""
    target = info.get("title_target_length", 80)
    errors = []
    expected = post_title(c, it)
    if title != expected:
        errors.append("标题与当前统一标题规则不一致")
    if not 1 <= len(title) <= target:
        errors.append(f"标题字符数 {len(title)}，要求 1–{target}")
    cast = draft.get("song") or {}
    if not (cast.get("artist") or info.get("artist")):
        errors.append("缺少歌手资料")
    if not (cast.get("title") or it.get("title")):
        errors.append("缺少歌名资料")
    from post_bili.upload import description
    body = description(draft)
    if not 1800 <= len(body) <= 2000:
        errors.append(f"简介字符数 {len(body)}，要求 1800–2000")
    if not all((draft.get("intro") or {}).get(k) for k in ("song", "performance", "lyrics")):
        errors.append("简介缺少歌曲、演出或歌词部分")
    subtitle = subtitle_line(c, it)
    if errors:
        raise ValueError("投稿格式检查失败：" + "；".join(errors))
    return {"title_length": len(title), "cover_subtitle": subtitle}
