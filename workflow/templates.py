"""Publication and cover copy contracts, shared by generators, UI and exports.

Video headers and posting titles have different field orders. Keeping named
templates here prevents a caller from reusing one as the other. Manual reviewed
copy remains authoritative; these rules generate and validate automatic copy.
"""
from types import MappingProxyType

BILI_TITLE_FIELDS = ("artist_zh", "song", "nicknames", "artist_en", "song_zh", "event")
BILI_KEYWORDS = ("欧美现场", "Billboard", "Grammy", "中英字幕")
TITLE_MAX = 80
DESC_MIN, DESC_MAX = 1800, 2000
TAG_MAX, TAG_LEN = 12, 20
INTRO_SECTIONS = ("song", "performance", "lyrics")
INTRO_FLOORS = {"intro_song": 350, "intro_performance": 350, "intro_lyrics": 500}
COVER_FORMATS = (("douyin", "3x4"), ("douyin", "4x3"), ("bili", "4x3"), ("bili", "16x9"))
COVER_SIZES = {("bili-ai", "16x9"): (1920, 1080), ("bili-ai", "4x3"): (1440, 1080),
               ("douyin-ai", "3x4"): (1080, 1440), ("douyin-ai", "4x3"): (1440, 1080)}
COVER_PATH_LABELS = MappingProxyType({(platform, ratio): f"{platform} {ratio}封面路径"
                                    for platform, ratio in COVER_FORMATS})


def ordered_bili_fields(**values):
    fields = []
    for name in BILI_TITLE_FIELDS:
        value = values.get(name)
        fields.extend(value if name == "nicknames" and value else [value])
    return [value for value in fields if value]


def valid_tags(tags):
    return (isinstance(tags, list) and len(tags) == TAG_MAX
            and all(isinstance(tag, str) and tag.strip() and len(tag) <= TAG_LEN for tag in tags)
            and len({tag.strip().casefold() for tag in tags}) == TAG_MAX)


def cover_text(song, song_zh, artist_en, event):
    """Approved cover/header order: original title, translation, English artist.

    Event and subtitle language are the footer. Chinese artist credits remain
    in publication copy and the approved landscape credit layout where used.
    """
    return {"song": song, "song_zh": song_zh or "", "en": artist_en.upper(),
            "event": event, "subtitles": "中英字幕"}


def compact_cover_text(song, artist, event, *, subtitle_override=None):
    """Current FIBO template for all four posting ratios, including 3x4.

    Only the canvas/crop and safe margins change between ratios. Publishing
    keywords and nicknames never enter the artwork's title or credit line.
    """
    return {"title": song, "subtitle": subtitle_override if subtitle_override is not None
            else " · ".join(value for value in (artist, event) if value)}


def cover_filename(platform, ratio, stamp, suffix):
    if (platform, ratio) not in COVER_PATH_LABELS:
        raise ValueError("不支持的投稿封面比例")
    return f"{platform}_ai_{ratio}_{stamp}{suffix.lower()}"
