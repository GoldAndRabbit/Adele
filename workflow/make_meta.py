#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投稿元数据 JSON：标题（固定格式，build_title 拼）、歌曲介绍、演出介绍、歌词介绍、标签、文件路径。

事实依据：posts/<name>/meta.json 里 yt-dlp 抓到的视频标题 / 简介 / 发布日期；
现场画面观察（stage_notes：均匀截 8 帧给 Qwen-VL，只描述看得到的造型、舞台、伴舞）；
歌词原文 + 中文翻译（lyrics_material）。模型负责整理成中文，不允许编造材料里没有的信息。

python workflow/make_meta.py --name sobaniirune --cover posts/sobaniirune/post/cover/cover_01.jpg
产物: posts/<name>/post/<name>.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import chat_json, vision_json  # noqa: E402

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
  "intro_lyrics": "歌词介绍",
  "tags": ["标签", ...]
}}

介绍要求：
- 简体中文，口吻自然，像 UP 主写给观众的简介；intro_song、intro_performance 各 150~300 字，intro_lyrics 300~500 字
- intro_song：歌曲背景、发行年份、成绩/影响、风格与主题
- intro_performance：这次演出/节目是什么、在哪里/什么形式；演出风格和氛围；舞台上特别的地方（布景、大屏、灯光特效、
  伴舞编排、走下舞台和观众互动等）；主唱的造型（服装、配饰、发型）。造型和舞台以「现场画面观察」为准，
  观察里没有的不写；观察里认不准的东西（比如大屏上是什么动物）就笼统说，不要坐实
- intro_lyrics：详细讲歌词——讲了一个什么故事 / 什么情绪，按段落怎么推进（主歌、副歌、桥段各写了什么），
  关键的意象、比喻、双关、俚语和文化背景，帮看不懂原文的观众读懂这首歌。以给出的「歌词」材料为准，
  可以引用其中的句子（原文 + 中文意思），引用必须逐字出自材料，不要编造材料里没有的歌词
- 只使用提供材料里的事实和广为人知的常识；材料里没有、你也不确定的，宁可不写，不要编数字和日期
- 频道/节目的通用口号、规则（如 THE FIRST TAKE 的“一支麦克风”）不是这次演出的事实，不要当作演出细节写
- 材料里只给了罗马字/英文的人名，保持原样，不要自己配汉字
- 不确定某人在演出中是唱还是说唱，就统一说“演唱”；避免“国民级”“家喻户晓”这类无依据的夸张
- 艺人英文名用官方英文/罗马字（如 Thelma Aoyama）
- intro_song、intro_performance 不引用歌词
- 不要介绍视频本身的制作（字幕收录了什么、字幕颜色/样式、4K/60帧/画质处理等），观众不需要；只写歌和演出
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


def lyrics_material(lyrics_txt, zh_cache=None, limit=6000):
    """歌词原文 + 中文翻译（translate_ass 的缓存）+ 翻译时写的歌曲解读，给模型写歌词介绍用。"""
    lines = [l.strip() for l in Path(lyrics_txt).read_text().splitlines() if l.strip()] if Path(lyrics_txt).exists() else []
    cache = json.loads(Path(zh_cache).read_text()) if zh_cache and Path(zh_cache).exists() else {}
    out = [f"{l}｜{cache[l]}" if cache.get(l) else l for l in lines]
    text = "\n".join(out)[:limit]
    brief = cache.get("__brief__")
    return (f"翻译时整理的歌曲解读：{brief}\n\n" if brief else "") + ("歌词（原文｜中文）：\n" + text if text else "")


def stage_notes(video, t0, t1, cache_path, n=8):
    """现场画面观察：在 [t0, t1] 里均匀截 n 帧给 Qwen-VL，只描述看得到的造型、舞台、伴舞和风格。结果缓存到 cache_path。"""
    cache_path = Path(cache_path)
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    import io
    import make_cover
    imgs = []
    for i in range(n):
        b = io.BytesIO()
        make_cover.grab(video, t0 + (t1 - t0) * (i + 0.5) / n).resize((960, 540)).save(b, "JPEG", quality=85)
        imgs.append(b.getvalue())
    notes = vision_json(
        "你是演唱会画面观察员。只描述图里确实看得到的东西，不猜测、不编造。大屏影像、道具、雕塑里的动物不要判断具体物种"
        "（低清截图里狼、熊、狗很容易认错），只写“动物形象”加颜色和大小；文字、标志看不清就不写。输出 JSON。",
        f"这 {n} 张是同一首歌现场演出按时间顺序截的画面。用中文描述，输出 JSON："
        '{"outfit": "主唱的造型（服装款式、颜色、材质、配饰、发型；中途换装就分别写）", '
        '"stage": "舞台布景、大屏画面、灯光、特效（火焰/烟雾/彩带等）、道具", '
        '"performers": "伴舞 / 乐手 / 嘉宾的人数、服装和动作，主唱有没有走下舞台、和观众互动", '
        '"style": "整体视觉风格和氛围（几个词）"}',
        imgs, label="现场画面")
    cache_path.write_text(json.dumps(notes, ensure_ascii=False, indent=1))
    return notes


def media_material(notes, lyrics):
    """拼进 user prompt 的两段材料：现场画面观察 + 歌词。"""
    out = ""
    if notes:
        out += "\n\n现场画面观察（从这段视频均匀截图后看到的，写演出介绍的造型 / 舞台以这个为准）：\n" + json.dumps(notes, ensure_ascii=False, indent=2)
    if lyrics:
        out += "\n\n" + lyrics
    return out


def intro_text(gen):
    """简介正文：歌曲介绍 + 演出介绍 + 歌词介绍，空行分开。"""
    return "\n\n".join(x.strip() for x in (gen.get("intro_song"), gen.get("intro_performance"), gen.get("intro_lyrics")) if x)


def reintro(name, note=None):
    """已有投稿只重写介绍（歌曲 + 演出 + 歌词三段），标题、歌名、标签不动。"""
    d = ROOT / "posts" / name
    dst = d / "post" / f"{name}.json"
    post = json.loads(dst.read_text())
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    source = {k: meta.get(k) for k in ("title", "channel", "upload_date", "duration", "webpage_url")}
    source["description"] = (meta.get("description") or "")[:4000]
    known = {"歌名": (post.get("song") or {}).get("title"), "艺人": (post.get("song") or {}).get("artist"),
             "演出": post.get("performance")}
    user = ("原视频信息：\n" + json.dumps(source, ensure_ascii=False, indent=2)
            + "\n\n已定的投稿信息（歌名、艺人以这个为准）：\n" + json.dumps(known, ensure_ascii=False, indent=2)
            + f"\n\n字幕：{' + '.join(post.get('subtitles') or [])}")
    if note:
        user += f"\n\n补充说明：{note}"
    dur = float(meta.get("duration") or 0) or None
    notes = stage_notes(d / "source.mp4", 0.0, dur, d / "stage_notes.json") if dur and (d / "source.mp4").exists() else None
    user += media_material(notes, lyrics_material(d / "lyrics.txt", d / "zh_cache.json"))
    gen = chat_json(SYSTEM_PROMPT, user, temperature=0.5, label=f"介绍 {name}")
    post["intro"] = {"song": gen.get("intro_song"), "performance": gen.get("intro_performance"), "lyrics": gen.get("intro_lyrics")}
    dst.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n")
    return post["intro"]


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
    p.add_argument("--reintro", action="store_true", help="已有投稿 JSON 只重写介绍（歌曲 + 演出 + 歌词），标题和标签不动")
    a = p.parse_args()
    if a.reintro:
        print(json.dumps(reintro(a.name, a.note), ensure_ascii=False, indent=2))
        return
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
    d = ROOT / "posts" / a.name
    dur = float(meta.get("duration") or 0) or None
    notes = stage_notes(d / "source.mp4", 0.0, dur, d / "stage_notes.json") if dur and (d / "source.mp4").exists() else None
    user += media_material(notes, lyrics_material(d / "lyrics.txt", d / "zh_cache.json"))

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
            "lyrics": gen.get("intro_lyrics"),
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
