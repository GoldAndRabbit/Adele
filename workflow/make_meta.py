#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投稿元数据 JSON：标题（固定格式，build_title 拼）、歌曲介绍、演出介绍、标签、文件路径。

事实依据只用 posts/<name>/meta.json 里 yt-dlp 抓到的视频标题 / 简介 / 发布日期，
模型负责整理成中文，不允许编造简介里没有的信息，也不引用歌词。

python workflow/make_meta.py --name sobaniirune --cover posts/sobaniirune/post/cover/cover_01.jpg
产物: posts/<name>/post/<name>.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import chat_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TITLE_PREFIX = "[4K60帧/Hi-Res]"
TITLE_MAX = 80  # B 站标题上限

SYSTEM_PROMPT = f"""你是 B 站音乐 UP 主「朝阳Adele」的投稿编辑。根据给出的原视频信息，输出 JSON：
{{
  "artist_zh": "艺人常用中文名（没有通行译名就用原名）",
  "artist_en": "艺人英文/罗马字名",
  "song_title": "歌名（保持原文）",
  "song_title_zh": "歌名的中文名：有通行译名用通行译名，没有就按意思简短意译（不要音译）；节目名、带编号的、和原文一样的填空字符串",
  "release_year": 发行年份数字，不确定填 null,
  "event": "演出/节目/演唱会名称",
  "event_zh": "演出的简短中文名，不带艺人名、带年份（如“马德里演唱会2026”“圣雷莫音乐节2020”“温布利演唱会2025”）",
  "event_en": "演出的简短英文/原文名，不带艺人名、带年份（如“Live from Madrid 2026”“Sanremo 2020”“THE FIRST TAKE”）",
  "event_date": "演出或视频发布日期 YYYY-MM-DD，不确定填 null",
  "intro_song": "歌曲介绍",
  "intro_performance": "演出介绍",
  "tags": ["标签", ...]
}}

介绍要求：
- 简体中文，各 120~250 字，口吻自然，像 UP 主写给观众的简介
- intro_song：歌曲背景、发行年份、成绩/影响、风格与主题
- intro_performance：这次演出/节目是什么、在哪里/什么形式、亮点（编曲、嘉宾、伴唱等）
- 只使用提供材料里的事实和广为人知的常识；材料里没有、你也不确定的，宁可不写，不要编数字和日期
- 频道/节目的通用口号、规则（如 THE FIRST TAKE 的“一支麦克风”）不是这次演出的事实，不要当作演出细节写
- 材料里只给了罗马字/英文的人名，保持原样，不要自己配汉字
- 不确定某人在演出中是唱还是说唱，就统一说“演唱”；避免“国民级”“家喻户晓”这类无依据的夸张
- 艺人英文名用官方英文/罗马字（如 Thelma Aoyama）
- 不要引用或改写任何歌词
- tags 8~12 个，中文为主，含艺人、歌名、节目名、“4K60帧”和字幕标签（字幕语言见“字幕”字段）"""


def build_title(artist_zh, artist_en, song, song_zh, event_zh, event_en, subs):
    """投稿标题（固定格式，代码拼，不让模型写）：
    [4K60帧/Hi-Res] {艺人中文} 《{歌名原文}》{艺人英文} {歌名中文} {演出中文名} {演出英文名} 中x字幕
    B 站上限 80 字，超了依次去掉：英文名里的年份 → 中文名里的年份 → 歌名中文 → 英文名 → 中文名 → 英文艺人名。"""
    import re
    no_year = lambda x: re.sub(r"\s*\(?\d{4}\)?$", "", x or "").strip()
    zh, en = (artist_zh or "").strip(), (artist_en or "").strip()
    head = [zh or en, f"《{song}》{en if en and en != zh else ''}".strip()]
    sz = "" if not song_zh or song_zh.strip().lower() == song.strip().lower() else song_zh.strip()
    ez, ee = (event_zh or "").strip(), (event_en or "").strip()
    for a in {zh, en} - {""}:   # 演出名不带艺人名（HKT48 7周年公演2018 -> 7周年公演2018）
        ez, ee = (re.sub(rf"^{re.escape(a)}\s*", "", x).strip() for x in (ez, ee))
    title = ""
    for parts in (head + [sz, ez, ee], head + [sz, ez, no_year(ee)], head + [sz, no_year(ez), no_year(ee)],
                  head + [ez, no_year(ee)], head + [no_year(ez), no_year(ee)], head + [ez], head + [no_year(ez)],
                  head + [sz], head, [zh or en, f"《{song}》"]):   # 艺人名 / 歌名太长（串烧、合作）：去掉演出名、再去掉英文艺人名
        title = " ".join([TITLE_PREFIX, *[x for x in dict.fromkeys(parts) if x], subs]).strip()
        if len(title) <= TITLE_MAX:
            return title
    print(f"警告：标题 {len(title)} 字，超过 {TITLE_MAX}，请手动缩短")
    return title


def subs_tag(langs):
    """['意大利语', '中文'] -> 中意字幕；['西班牙语', '英语', '中文'] -> 中西英字幕。"""
    xs = [x for x in langs if x and x not in ("中文", "原文")]
    return f"中{''.join(x[0] for x in xs)}字幕" if xs else ""


TITLE_FIELDS_PROMPT = """根据投稿信息，给出标题用的字段，输出 JSON：
{"artist_zh": "艺人常用中文名（没有通行译名就用原名）", "artist_en": "艺人英文/罗马字名",
 "song_title_zh": "歌名的中文名：有通行译名用通行译名，没有就按意思简短意译（不要音译）；节目名、带编号的、和原文一样的填空字符串",
 "event_zh": "演出的简短中文名，不带艺人名、带年份（如“马德里演唱会2026”“圣雷莫音乐节2020”“温布利演唱会2025”）",
 "event_en": "演出的简短英文/原文名，不带艺人名、带年份（如“Live from Madrid 2026”“Sanremo 2020”“THE FIRST TAKE”）"}
只用给出的信息，不要编造。"""


def retitle(name):
    """已有投稿只换标题（按新格式），介绍、标签不动。"""
    dst = ROOT / "posts" / name / "post" / f"{name}.json"
    post = json.loads(dst.read_text())
    info = {k: post.get(k) for k in ("title", "song", "performance", "intro", "source")}
    f = chat_json(TITLE_FIELDS_PROMPT, json.dumps(info, ensure_ascii=False, indent=2), temperature=0.2, label="标题字段")
    song = post.get("song") or {}
    perf = post.get("performance") or {}
    song.update({"artist_zh": f.get("artist_zh") or song.get("artist_zh"), "title_zh": f.get("song_title_zh") or ""})
    perf.update({"event_zh": f.get("event_zh"), "event_en": f.get("event_en")})
    post["song"], post["performance"] = song, perf
    post["title"] = build_title(song.get("artist_zh"), f.get("artist_en") or song.get("artist"), song.get("title"),
                                song.get("title_zh"), perf.get("event_zh"), perf.get("event_en"),
                                subs_tag(post.get("subtitles") or []))
    dst.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n")
    return post["title"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--subtitle-langs", default="", help="字幕语言，如 '日语,中文'；默认从字幕文件推断")
    p.add_argument("--video", help="成品视频，默认 post/<name>/<name> 4K60FPS Sub-WaterMark.mp4")
    p.add_argument("--cover", help="选定的封面")
    p.add_argument("--note", help="补充给模型的信息（如演唱会名称、你想强调的点）")
    p.add_argument("--retitle", action="store_true", help="已有投稿 JSON 只按新格式重写标题，介绍和标签不动")
    a = p.parse_args()
    if a.retitle:
        t = retitle(a.name)
        print(f"{len(t)} 字：{t}")
        return

    meta_path = ROOT / "posts" / a.name / "meta.json"
    if not meta_path.exists():
        sys.exit(f"缺少 {meta_path}（download 阶段生成）")
    meta = json.loads(meta_path.read_text())

    source = {k: meta.get(k) for k in ("title", "channel", "upload_date", "duration", "tags", "webpage_url")}
    source["description"] = (meta.get("description") or "")[:4000]
    user = "原视频信息：\n" + json.dumps(source, ensure_ascii=False, indent=2)
    langs = [x for x in a.subtitle_langs.split(",") if x] or ["原文", "中文"]
    user += f"\n\n字幕：{' + '.join(langs)}（标签写作“中{langs[0][0]}字幕”这类形式）"
    if a.note:
        user += f"\n\n补充说明：{a.note}"

    gen = chat_json(SYSTEM_PROMPT, user, temperature=0.5, label="元数据")
    title = build_title(gen.get("artist_zh"), gen.get("artist_en"), gen.get("song_title") or "",
                        gen.get("song_title_zh"), gen.get("event_zh"), gen.get("event_en"), subs_tag(langs))

    video = Path(a.video) if a.video else ROOT / "posts" / a.name / "post" / f"{a.name} 4K60FPS Sub-WaterMark.mp4"
    # 16:9 和 4:3 两种封面（make_cover.py 同时生成 cover_XX.jpg 和 cover_XX_4x3.jpg）
    cover = a.cover or (f"posts/{a.name}/post/cover/cover_01.jpg"
                        if (ROOT / "posts" / a.name / "post" / "cover" / "cover_01.jpg").exists() else None)
    cover_43 = cover[:-4] + "_4x3.jpg" if cover else None
    out = {
        "name": a.name,
        "title": title,
        "song": {
            "title": gen.get("song_title"),
            "artist": gen.get("artist_en"),
            "artist_zh": gen.get("artist_zh"),
            "title_zh": gen.get("song_title_zh") or "",
            "release_year": gen.get("release_year"),
        },
        "performance": {
            "event": gen.get("event"),
            "event_zh": gen.get("event_zh"),
            "event_en": gen.get("event_en"),
            "date": gen.get("event_date"),
        },
        "intro": {
            "song": gen.get("intro_song"),
            "performance": gen.get("intro_performance"),
        },
        "tags": gen.get("tags", []),
        "subtitles": langs,
        "spec": {"resolution": "3840x2160", "fps": 60, "audio": "FLAC 48kHz/24bit (Hi-Res)"},
        "files": {
            "video": str(video.relative_to(ROOT)) if video.is_relative_to(ROOT) else str(video),
            "cover": cover,
            "cover_4x3": cover_43 if cover_43 and (ROOT / cover_43).exists() else None,
            "subtitle": f"posts/{a.name}/lyrics.ass",
        },
        "source": {
            "url": meta.get("webpage_url"),
            "title": meta.get("title"),
            "channel": meta.get("channel"),
        },
    }
    dst = ROOT / "posts" / a.name / "post" / f"{a.name}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"写入 {dst}")


if __name__ == "__main__":
    main()
