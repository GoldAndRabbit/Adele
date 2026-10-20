# -*- coding: utf-8 -*-
"""v2 路径约定：一场演唱会的所有文件都在 concerts/<slug>/ 下，每首歌一个 songs/<nn>_<slug>/（布局同 v1 的 posts/<name>/）。"""

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONCERTS = ROOT / "concerts"
POSTS = ROOT / "posts"   # 每首歌的目录（单曲和演唱会里的歌都在这里，成品在 posts/<歌名>/post/）
VENV_PY = ROOT / ".venv" / "bin" / "python"
SEP_PY = ROOT / ".venv-sep" / "bin" / "python"


def slugify(text, n=32):
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:n].rstrip("_") or "song"


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path, data):
    """先写临时文件再改名：网页和流水线同时读写时不会读到半截文件。"""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


class Concert:
    """concerts/<slug>/
         concert.json   源文件、时长、fps、艺人、日期、场馆        setlist.txt / setlist.json   歌单
         source.mp4     无损 remux（网页预览、高清切片都用它）    captions.srt   内嵌字幕轨
         audio.flac     整场 48k/24bit                           vocals.wav     整场人声
         segments.json  每首歌的起止                              review.json    人工审核结果
         songs/<nn>_<slug>    每首歌：指向 posts/<nn>_<slug>/ 的软链接（audio.flac vocals.wav lyrics.txt exp_v4/ covers/ post/）
    """

    def __init__(self, slug):
        self.slug = slug
        self.dir = CONCERTS / slug
        self.songs = self.dir / "songs"
        self.logs = self.dir / "logs"

    def __getattr__(self, key):
        files = {
            "info": "concert.json", "source": "source.mp4", "captions": "captions.srt",
            "audio": "audio.flac", "vocals": "vocals.wav", "setlist_txt": "setlist.txt",
            "setlist": "setlist.json", "segments": "segments.json", "review": "review.json",
            "captions_lines": "captions_lines.json", "features": "features.npz",
        }
        if key in files:
            return self.dir / files[key]
        raise AttributeError(key)

    def load(self, key, default=None):
        return read_json(getattr(self, key), default)

    def items(self):
        return (self.load("setlist") or {}).get("items", [])

    def song_items(self):
        return [it for it in self.items() if it["kind"] == "song"]

    def song_dir(self, it):
        return self.songs / it["name"]

    def make_song_dir(self, it):
        """新歌的目录建在 posts/<歌名>/，songs/<歌名> 是指过去的软链接（找成品只看 posts/）。"""
        d = self.song_dir(it)
        if not d.exists() and not d.is_symlink():
            real = POSTS / it["name"]
            real.mkdir(parents=True, exist_ok=True)
            self.songs.mkdir(parents=True, exist_ok=True)
            d.symlink_to(real)
        return d

    def item(self, key):
        """按序号（8 / "08"）或目录名找歌单条目。"""
        for it in self.items():
            if str(key) in (it["name"], str(it["idx"]), f"{it['idx']:02d}"):
                return it
        raise KeyError(f"歌单里没有 {key}")
