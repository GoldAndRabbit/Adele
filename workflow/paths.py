# -*- coding: utf-8 -*-
"""项目路径约定：一首歌的所有文件都在 songs/<name>/ 下，模型都在 models/ 下。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "workflow"
SONGS = ROOT / "songs"
MODELS = ROOT / "models"
ASSETS = ROOT / "assets"
BIN = ROOT / "bin"


class Song:
    """songs/<name>/
         lyrics.txt          参考歌词（Genius）          lyrics.srt   对齐后的原文字幕
         official.srt        官方带时间字幕（可选）      lyrics.ass   双语字幕
         source.mp4 source.*.srt meta.json               下载
         video_1080.mp4 audio.flac vocals.wav            中间产物
         zh_cache.json lyrics_source reports/ frames_*/  中间产物
         post/<name> 4K60FPS Sub-WaterMark.mp4  post/<name>.json  post/cover/   成品
    """

    def __init__(self, name):
        self.name = name
        self.dir = SONGS / name
        self.reports = self.dir / "reports"
        self.post = self.dir / "post"
        self.cover = self.post / "cover"

    def __getattr__(self, key):
        files = {
            "lyrics_txt": "lyrics.txt", "lyrics_srt": "lyrics.srt", "lyrics_ass": "lyrics.ass",
            "official_srt": "official.srt", "lyrics_source": "lyrics_source",
            "source": "source.mp4", "meta": "meta.json", "video_1080": "video_1080.mp4",
            "audio": "audio.flac", "vocals": "vocals.wav", "zh_cache": "zh_cache.json",
            "frames_in": "frames_in", "frames_out": "frames_out", "subs": "subs.ass",
            "cover_art": "cover_art.png",
        }
        if key in files:
            return self.dir / files[key]
        raise AttributeError(key)

    def video(self, tag=None):
        return self.post / f"{self.name} 4K60FPS Sub-WaterMark{' ' + tag if tag else ''}.mp4"

    @property
    def json(self):
        return self.post / f"{self.name}.json"

    def mkdirs(self):
        for d in (self.dir, self.reports, self.post):
            d.mkdir(parents=True, exist_ok=True)
        return self
