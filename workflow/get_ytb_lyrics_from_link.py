#!/usr/bin/env python3
"""YouTube 音乐视频 → Genius 歌词 → ori_lyrics/<name>.txt。"""

import argparse
from difflib import SequenceMatcher
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 30


def validate_url(url, genius=False):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = {"genius.com", "www.genius.com"} if genius else {
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
    }
    if parsed.scheme not in {"https", "http"} or host not in allowed:
        raise ValueError("请输入有效的 Genius 歌词页链接" if genius else "请输入有效的 YouTube 视频链接")
    return url


def clean_title(title):
    # 只清理视频格式标签，保留 remix / acoustic 等歌曲版本信息。
    noise = r"official|music video|lyric(?:s)?(?: video)?|visuali[sz]er|audio|video|4k|8k|hd|hq|1080p|720p|mv|字幕|live|explicit|clean version"
    title = re.sub(r"[\[(]([^\])]+)[\])]", lambda m: "" if re.search(
        rf"\b(?:{noise})\b", m[1], re.I) else m[0], title)
    title = re.sub(rf"\s*\|\s*(?:{noise}).*$", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" \"'“”")


def identify_song(info):
    artist = info.get("artist") or ", ".join(info.get("artists") or [])
    if info.get("track"):
        return clean_title(info["track"]), artist or ""
    title = clean_title(info.get("title") or "")
    # 节目上传常用 Artist "Song" 日期 | 节目名，不把日期里的 / 当作分隔符。
    quoted = re.match(r'^(.+?)\s+["“](.+?)["”](?:\s|$)', title)
    if quoted:
        return clean_title(quoted[2]), artist or quoted[1].strip()
    title = re.sub(r"\s+\|\s+.*$", "", title)
    title = re.sub(r"\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$", "", title)
    parts = re.split(r"\s+[-–—/]\s+", title, maxsplit=1)
    if len(parts) == 2:
        return clean_title(parts[1]), artist or parts[0].strip()
    # 普通上传者不一定是歌手；只使用明确的艺人频道命名。
    channel = info.get("channel") or info.get("uploader") or ""
    if not artist and (channel.endswith(" - Topic") or channel.upper().endswith("VEVO")):
        artist = re.sub(r"(?: - Topic|VEVO)$", "", channel, flags=re.I)
    return title, artist or ""


def youtube_info(url, session, cookies=None):
    options = {"quiet": True, "no_warnings": True, "skip_download": True,
               "noplaylist": True, "socket_timeout": TIMEOUT, "retries": 2}
    if cookies:
        options["cookiefile"] = cookies
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("_type") in {"playlist", "multi_video"}:
            raise ValueError("请提供单个音乐视频链接，不支持播放列表")
        return info
    except DownloadError:
        print("yt-dlp 获取元数据失败，尝试 YouTube oEmbed…", file=sys.stderr)
        response = session.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"},
                               timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return {"title": data["title"], "channel": data.get("author_name", "")}


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def similarity(a, b):
    a, b = normalized(a), normalized(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def search_song(session, title, artist, token=None):
    endpoint = "https://api.genius.com/search" if token else "https://genius.com/api/search/song"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = session.get(endpoint, params={"q": f"{artist} {title}".strip()},
                           headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()["response"]
    hits = data.get("hits", [])
    for section in data.get("sections", []):
        if section.get("type") == "song":
            hits.extend(section.get("hits", []))
    ranked = []
    for hit in hits:
        song = hit.get("result", {})
        if song.get("instrumental") or song.get("lyrics_state") not in {None, "complete"}:
            continue
        name = song.get("title", "")
        if re.search(r"translation|romanization|翻译|ローマ字", name, re.I):
            continue
        singer = song.get("primary_artist", {}).get("name", "")
        title_score = similarity(title, name)
        artist_score = similarity(artist, singer) if artist else 1.0
        if title_score >= 0.72 and artist_score >= 0.55 and song.get("url"):
            ranked.append((0.75 * title_score + 0.25 * artist_score, song))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        candidates = "；".join(hit.get("result", {}).get("full_title", "") for hit in hits[:5])
        raise ValueError(f"没有可靠的歌曲匹配。候选：{candidates or '无'}。"
                         "请用 --title / --artist 修正，或用 --genius-url 指定歌词页")
    if len(ranked) > 1 and ranked[0][1].get("id") != ranked[1][1].get("id") and ranked[0][0] - ranked[1][0] < 0.04:
        raise ValueError("搜索结果存在多个相近版本，请用 --artist 或 --genius-url 指定")
    return ranked[0][1]


def extract_lyrics(html, keep_sections=False):
    soup = BeautifulSoup(html, "html.parser")
    for unwanted in soup.select('[data-exclude-from-selection="true"], [class*="LyricsHeader"], script, style'):
        unwanted.decompose()
    containers = soup.select('[data-lyrics-container="true"]') or soup.select("div.lyrics")
    if not containers:
        raise ValueError("Genius 页面未找到歌词区域，可能被访问限制或页面结构已变更")
    blocks = []
    for container in containers:
        for br in container.find_all("br"):
            br.replace_with("\n")
        # 内联注解链接不能变成新行。
        blocks.append(container.get_text().strip())
    lyrics = "\n\n".join(block for block in blocks if block)
    lyrics = lyrics.replace("\r", "").replace("\u200b", "")
    if not keep_sections:
        lyrics = re.sub(r"(?m)^\s*\[[^\]\n]+\]\s*$", "", lyrics)
    lyrics = "\n".join(line.rstrip() for line in lyrics.splitlines())
    lyrics = re.sub(r"\n{3,}", "\n\n", lyrics).strip()
    if not lyrics:
        raise ValueError("Genius 歌词区域为空，不保存文件")
    return lyrics + "\n"


def output_path(name):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if stem.lower().endswith(".txt"):
        stem = stem[:-4].rstrip(" .")
    if not stem:
        raise ValueError("输出文件名不能为空")
    # 限制 UTF-8 文件名的字节长度。
    stem = stem.encode("utf-8")[:200].decode("utf-8", errors="ignore")
    return ROOT / "ori_lyrics" / f"{stem}.txt"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube 音乐视频链接")
    parser.add_argument("--title", help="手动指定歌名")
    parser.add_argument("--artist", help="手动指定歌手")
    parser.add_argument("--name", help="输出文件名，例如 emptiness_machine（无需 .txt）")
    parser.add_argument("--genius-url", help="直接指定 Genius 歌词页，跳过搜索")
    parser.add_argument("--cookies", help="yt-dlp 使用的 Netscape cookies 文件")
    parser.add_argument("--keep-sections", action="store_true", help="保留 [Verse] / [Chorus] 等标签")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有歌词文件")
    args = parser.parse_args(argv)
    try:
        validate_url(args.url)
        with requests.Session() as session:
            session.headers["User-Agent"] = "Mozilla/5.0 (compatible; YouTubeLyrics/1.0)"
            if args.genius_url:
                genius_url = validate_url(args.genius_url, genius=True)
                title = args.title or urlparse(genius_url).path.strip("/").removesuffix("-lyrics")
                artist = args.artist or ""
            else:
                if args.title and args.artist:
                    title, artist = args.title, args.artist
                else:
                    title, artist = identify_song(youtube_info(args.url, session, args.cookies))
                    title, artist = args.title or title, args.artist if args.artist is not None else artist
                if not title.strip():
                    raise ValueError("无法识别歌名，请提供 --title 和 --artist")
                print(f"搜索：{artist} — {title}")
                song = search_song(session, title, artist, os.environ.get("GENIUS_ACCESS_TOKEN"))
                title = song["title"]
                artist = song.get("primary_artist", {}).get("name", artist)
                genius_url = validate_url(song["url"], genius=True)
            dest = output_path(args.name or f"{artist} - {title}".strip(" -"))
            if dest.exists() and not args.overwrite:
                raise FileExistsError(f"文件已存在：{dest}；如需覆盖请添加 --overwrite")
            print(f"歌词页：{genius_url}")
            response = session.get(genius_url, timeout=TIMEOUT)
            response.raise_for_status()
            lyrics = extract_lyrics(response.text, args.keep_sections)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w" if args.overwrite else "x", encoding="utf-8") as handle:
            handle.write(lyrics)
        print(f"已保存：{dest}（{len(lyrics.splitlines())} 行）")
        return 0
    except (requests.RequestException, DownloadError, ValueError, KeyError, OSError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
