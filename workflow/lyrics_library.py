"""Versioned local archive shared by Genius import and concert subtitle translation."""
import hashlib
import json
import re
import sqlite3
import unicodedata
import zlib
from contextlib import closing
from pathlib import Path

from workflow.live.paths import POSTS, ROOT, read_json

DB = POSTS / ".lyrics-library" / "archive.sqlite3"


def identity(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=30)
    db.execute("""CREATE TABLE IF NOT EXISTS versions (
        artist TEXT, title TEXT, kind TEXT, source TEXT, digest TEXT, payload BLOB,
        UNIQUE(artist,title,kind,source,digest))""")
    return db


def store(artist, title, kind, source, data):
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    with closing(connect()) as db, db:
        db.execute("INSERT OR IGNORE INTO versions VALUES (?,?,?,?,?,?)",
                   (identity(artist), identity(title), kind, source,
                    hashlib.sha256(blob).hexdigest(), zlib.compress(blob)))


def genius_lookup(artist, title, url=None):
    if not url and not (artist and title):
        return None
    with closing(connect()) as db:
        if url:
            rows = db.execute("SELECT source,payload FROM versions WHERE kind='genius' AND source=? ORDER BY rowid DESC LIMIT 1", (url,)).fetchall()
        else:
            rows = db.execute("SELECT source,payload FROM versions WHERE artist=? AND title=? AND kind='genius' ORDER BY rowid DESC",
                              (identity(artist), identity(title))).fetchall()
    if rows and len({r[0] for r in rows}) == 1:
        return json.loads(zlib.decompress(rows[0][1]))


def song_identity(d):
    info = read_json(d / "song.json", {}) or {}
    draft = read_json(d / "post_draft.json", {}) or read_json(d / "post" / (d.name + ".json"), {}) or {}
    song = draft.get("song") or {}
    return info.get("artist") or song.get("artist"), info.get("title") or song.get("title")


def archive_translation(d, result):
    artist, title = song_identity(d)
    if artist and title and result.get("units"):
        store(artist, title, "zh", str(d.resolve()), result)


def translation_memory(d):
    artist, title = song_identity(d)
    if not (artist and title):
        return {}
    memory, locked = {}, set()
    with closing(connect()) as db:
        rows = db.execute("SELECT payload FROM versions WHERE artist=? AND title=? AND kind='zh' AND source<>? ORDER BY rowid DESC",
                          (identity(artist), identity(title), str(d.resolve())))
        for (payload,) in rows:
            for u in json.loads(zlib.decompress(payload)).get("units", []):
                orig = u.get("orig")
                zh = u.get("v2_final")
                if not orig or not zh or u.get("type") != "歌词" or u.get("dropped"):
                    continue
                if orig in locked or (orig in memory and not u.get("locked")):
                    continue
                memory[orig] = dict(v1=u.get("v1") or zh, v2=zh, v3=u.get("v3_final") or zh)
                if u.get("locked"):
                    locked.add(orig)
    return memory


def backfill():
    seen = set()
    for pattern, base in [("*/songs/*", ROOT/"concerts"), ("*", POSTS), ("*/*", POSTS)]:
        for path in base.glob(pattern):
            d = path.resolve()
            if d in seen or not d.is_dir():
                continue
            seen.add(d)
            result = read_json(d/"subs/translation/result.json")
            if result:
                archive_translation(d, result)
            info = read_json(d/"song.json", {}) or {}
            facts = info.get("genius") or read_json(d/"genius_facts.json", []) or []
            urls = info.get("genius_urls") or [(fact or {}).get("url") for fact in facts]
            if not urls or not (d/"lyrics.txt").is_file():
                continue
            artist, title = song_identity(d)
            titles = info.get("parts") or [title]
            plain = (d/"lyrics.txt").read_text().strip()
            sec_path = d/"lyrics_sections.txt"
            if not sec_path.is_file() or not artist or not title:
                continue
            sections = sec_path.read_text().strip()
            if len(urls) == 1 and len(titles) == 1:
                parts = [(plain, sections)]
            else:
                texts = plain.split("\n\n\n")
                blocks = re.split(r"(?m)^\[\d+·[^\]\n]+\]\n(?=\[\d+·)", sections)
                if not (len(texts) == len(blocks)-1 == len(titles) == len(urls)):
                    continue
                parts = [(a, re.sub(r"(?m)^\[\d+·", "[", b)) for a,b in zip(texts,blocks[1:])]
            for i, ((a,b), part, url) in enumerate(zip(parts,titles,urls)):
                if url and url.startswith(("https://genius.com/", "https://www.genius.com/")) and a.strip() and b.strip():
                    data = dict(url=url, plain=a.strip()+"\n", sections=b.strip()+"\n", facts=facts[i] if i<len(facts) else None)
                    store(artist, part, "genius", url, data)


if __name__ == "__main__":
    backfill()
