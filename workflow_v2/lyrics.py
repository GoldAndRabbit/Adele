# -*- coding: utf-8 -*-
"""lyrics：按歌单逐首从 Genius 取歌词（用歌单的歌名 + 歌手直接搜，不从视频标题反推）。
产物 songs/<nn>/lyrics.txt、lyrics_sections.txt、song.json；串烧把各段歌词按顺序拼起来，段落名加上第几首。"""

import re

import requests

from .paths import write_json, read_json

STOP = {
    "es": {"que", "de", "no", "me", "la", "el", "y", "te", "lo", "mi", "en", "un", "una", "por", "con", "tu", "yo", "se", "es", "para"},
    "en": {"the", "you", "i", "and", "to", "me", "my", "it", "a", "in", "of", "your", "is", "on", "that", "be", "for", "with", "this"},
}


def guess_lang(text):
    words = re.findall(r"[a-záéíóúñü']+", text.lower())
    score = {k: sum(w in v for w in words) for k, v in STOP.items()}
    return max(score, key=score.get)


def candidates(title):
    """先用原标题搜，搜不到再去掉括号里的副标题（Suerte (Whenever, Wherever) -> Suerte）。"""
    yield title
    short = re.sub(r"\s*\([^)]*\)", "", title).strip()
    if short != title:
        yield short


def search(session, title, artist):
    """Genius 搜索，返回歌曲条目（含 url、发行日期、艺人）。"""
    import os
    import get_ytb_lyrics_from_link as g
    err = None
    for t in candidates(title):
        try:
            return g.search_song(session, t, artist, os.environ.get("GENIUS_ACCESS_TOKEN"))
        except ValueError as e:
            err = e
    raise ValueError(f"{artist} — {title}: {err}")


def song_facts(song):
    """Genius 条目里可以当事实写进介绍的字段。"""
    if not song:
        return None
    return {
        "full_title": song.get("full_title"), "artists": song.get("artist_names"),
        "primary_artist": (song.get("primary_artist") or {}).get("name"),
        "featured": [a.get("name") for a in song.get("featured_artists") or []],
        "release_date": song.get("release_date_for_display"), "url": song.get("url"),
    }


# Genius 歌词里夹着 U+2005 等特殊空格：看着一样、字符串不相等（同一句会被当成两句），统一成普通空格
SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
# Genius 歌词里混着长得一样的西里尔字母（quе 的 е 是 U+0435）：显示没区别，但匹配、翻译缓存都会当成另一个词
HOMOGLYPHS = str.maketrans("еаорсхуіЕАОРСХІ", "eaopcxyiEAOPCXI")


def clean_text(s):
    return SPACES.sub(" ", s).translate(HOMOGLYPHS)


def fetch_part(session, title, artist, genius_url=None):
    import get_ytb_lyrics_from_link as g
    song = None
    if not genius_url:
        song = search(session, title, artist)
        genius_url = song["url"]
    html = session.get(genius_url, timeout=30)
    html.raise_for_status()
    plain, secs = (clean_text(g.extract_lyrics(html.text, k)) for k in (False, True))
    return genius_url, plain, secs, song_facts(song)


def stage_lyrics(c, a):
    from llm import load_env
    load_env()
    sel = set(a.songs) if a.songs else None
    failed = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0 (compatible; YouTubeLyrics/1.0)"
        for it in c.song_items():
            if sel and not ({it["name"], str(it["idx"]), f"{it['idx']:02d}"} & sel):
                continue
            d = c.song_dir(it)
            d.mkdir(parents=True, exist_ok=True)
            info = read_json(d / "song.json", {})
            info.update({k: it[k] for k in ("idx", "name", "title", "artist", "parts", "notes")})
            if (d / "lyrics.txt").exists() and not a.force:
                print(f"{it['idx']:>2} {it['title']}: 已有 lyrics.txt")
            else:
                plain, secs, urls, facts = [], [], [], []
                try:
                    for k, part in enumerate(it["parts"], 1):
                        url, txt, sec, fact = fetch_part(session, part, it["artist"], it.get("genius_url") if len(it["parts"]) == 1 else None)
                        urls.append(url)
                        facts.append(fact)
                        plain.append(txt.strip())
                        if len(it["parts"]) > 1:
                            # 串烧：各首的段落名加上序号，避免两首的 [Chorus] 被当成同一段
                            sec = re.sub(r"(?m)^\s*\[", f"[{k}·", sec)
                            sec = f'[{k}·{part}]\n' + sec
                        secs.append(sec.strip())
                except (ValueError, requests.RequestException) as e:
                    print(f"{it['idx']:>2} {it['title']}: 取歌词失败 {e}\n    在 setlist.txt 这一行加 genius=<歌词页>，或手动放 {d / 'lyrics.txt'}")
                    failed.append(it["title"])
                    write_json(d / "song.json", info)
                    continue
                (d / "lyrics.txt").write_text("\n\n\n".join(plain) + "\n", encoding="utf-8")  # 串烧各首之间空两行
                (d / "lyrics_sections.txt").write_text("\n\n".join(secs) + "\n", encoding="utf-8")
                (d / "lyrics_source").write_text("reference")
                info["genius_urls"] = urls
                info["genius"] = facts
                print(f"{it['idx']:>2} {it['title']}: {len(plain[0].splitlines())} 行  {' '.join(urls)}")
            if "genius" not in info and not it.get("genius_url"):  # 早先取的歌词没存歌曲信息：补搜一次
                try:
                    info["genius"] = [song_facts(search(session, part, it["artist"])) for part in it["parts"]]
                except (ValueError, requests.RequestException) as e:
                    print(f"    Genius 歌曲信息没取到：{e}")
            text = (d / "lyrics.txt").read_text(encoding="utf-8")
            info["lang"] = info.get("lang_override") or guess_lang(text)
            # 串烧各段语言可能不同（Empire 英语 / Inevitable 西语）：对齐用主语言，字幕标签写全
            parts = [x for x in text.split("\n\n\n")] if len(it["parts"]) > 1 else [text]
            info["langs"] = list(dict.fromkeys([info["lang"]] + [guess_lang(x) for x in parts]))
            write_json(d / "song.json", info)
    if failed:
        print(f"\n⚠ {len(failed)} 首没取到歌词：{', '.join(failed)}")
