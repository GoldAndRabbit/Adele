#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投稿元数据 JSON：标题（固定格式）、歌曲介绍、演出介绍、标签、文件路径。

事实依据只用 work/<name>/meta.json 里 yt-dlp 抓到的视频标题 / 简介 / 发布日期，
模型负责整理成中文，不允许编造简介里没有的信息，也不引用歌词。

python pipeline/make_meta.py --name sobaniirune --cover post/covers/sobaniirune/art/cover_01.jpg
产物: post/<name>.json
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
  "title": "投稿标题",
  "artist_zh": "艺人常用中文名（没有通行译名就用原名）",
  "artist_en": "艺人英文/罗马字名",
  "song_title": "歌名（保持原文）",
  "release_year": 发行年份数字，不确定填 null,
  "event": "演出/节目/演唱会名称",
  "event_date": "演出或视频发布日期 YYYY-MM-DD，不确定填 null",
  "intro_song": "歌曲介绍",
  "intro_performance": "演出介绍",
  "tags": ["标签", ...]
}}

标题格式（务必遵守，总长不超过 {TITLE_MAX} 字）：
{TITLE_PREFIX} 艺人中文名《歌名》艺人英文名. 搜索关键词
历史标题示例：
- {TITLE_PREFIX} 夏奇拉《Bzrp Music Sessions, Vol. 53》Shakira. bzrpmusicsession diss皮克
- {TITLE_PREFIX} Lorde《Favourite Daughter》洛德 favoritedaughter 现场 Virgin Music Live
- {TITLE_PREFIX} OneRepublic《Apologize》共和时代 apologize 共和乐队
- {TITLE_PREFIX} 巴黎圣日耳曼队歌《Allez PSG》大巴黎队歌 Paris Saint-Germain
关键词部分：歌名去空格的小写写法、艺人别名、节目名、“现场”等便于搜索的词。

介绍要求：
- 简体中文，各 120~250 字，口吻自然，像 UP 主写给观众的简介
- intro_song：歌曲背景、发行年份、成绩/影响、风格与主题
- intro_performance：这次演出/节目是什么、在哪里/什么形式、亮点（编曲、嘉宾、伴唱等）
- 只使用提供材料里的事实和广为人知的常识；材料里没有、你也不确定的，宁可不写，不要编数字和日期
- 频道/节目的通用口号、规则（如 THE FIRST TAKE 的“一支麦克风”）不是这次演出的事实，不要当作演出细节写
- 材料里只给了罗马字/英文的人名，保持原样，不要自己配汉字
- 不确定某人在演出中是唱还是说唱，就统一说“演唱”；避免“国民级”“家喻户晓”这类无依据的夸张
- 艺人英文名用官方英文/罗马字（如 Thelma Aoyama），关键词里不要重复歌名原文；有通行中文译名的歌名可作关键词
- 不要引用或改写任何歌词
- tags 8~12 个，中文为主，含艺人、歌名、节目名、“4K60帧”和字幕标签（字幕语言见“字幕”字段）"""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--subtitle-langs", default="", help="字幕语言，如 '日语,中文'；默认从字幕文件推断")
    p.add_argument("--video", help="成品视频，默认 post/<name> 4K60FPS Sub-WaterMark.mp4")
    p.add_argument("--cover", help="选定的封面")
    p.add_argument("--note", help="补充给模型的信息（如演唱会名称、你想强调的点）")
    a = p.parse_args()

    meta_path = ROOT / "work" / a.name / "meta.json"
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
    title = gen.get("title", "").strip()
    if not title.startswith(TITLE_PREFIX):
        title = f"{TITLE_PREFIX} {title}"
    if len(title) > TITLE_MAX:
        print(f"警告：标题 {len(title)} 字，超过 {TITLE_MAX}，请手动缩短")

    video = Path(a.video) if a.video else ROOT / "post" / f"{a.name} 4K60FPS Sub-WaterMark.mp4"
    out = {
        "name": a.name,
        "title": title,
        "song": {
            "title": gen.get("song_title"),
            "artist": gen.get("artist_en"),
            "artist_zh": gen.get("artist_zh"),
            "release_year": gen.get("release_year"),
        },
        "performance": {
            "event": gen.get("event"),
            "date": gen.get("event_date"),
        },
        "intro": {
            "song": gen.get("intro_song"),
            "performance": gen.get("intro_performance"),
        },
        "tags": gen.get("tags", []),
        "subtitles": langs,
        "spec": {"resolution": "3840x2160", "fps": 60, "audio": "AAC 320k"},
        "files": {
            "video": str(video.relative_to(ROOT)) if video.is_relative_to(ROOT) else str(video),
            "cover": a.cover,
            "subtitle": f"lyrics/{a.name}.ass",
        },
        "source": {
            "url": meta.get("webpage_url"),
            "title": meta.get("title"),
            "channel": meta.get("channel"),
        },
    }
    dst = ROOT / "post" / f"{a.name}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"写入 {dst}")


if __name__ == "__main__":
    main()
