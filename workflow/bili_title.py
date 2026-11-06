"""Deterministic Bilibili title, independent from Douyin metadata."""
import re

NICKNAMES = {"Katy Perry": ("水果姐",), "Taylor Swift": ("霉霉",)}
VERSION = 'artist-song-nickname-translation-year-event-20261106'


def build_title(artist_zh, artist_en, song, song_zh, event_zh, event_en, subs=None, *, year=None, nicknames=None):
    artist = re.sub(r'\s*(?:、|，|&|与)\s*', ' & ', (artist_en or artist_zh or '').strip())
    aliases = [nicknames] if isinstance(nicknames, str) else list(nicknames or [])
    for name in re.split(r'\s+&\s+|\s+(?:feat\.?|ft\.?)\s+', artist, flags=re.I):
        aliases.extend(NICKNAMES.get(name, ()))
    aliases = list(dict.fromkeys(x.strip() for x in aliases if x and x.strip()))
    zh, en = (event_zh or '').strip(), (event_en or '').strip()
    found = re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', str(year or '') + ' ' + en + ' ' + zh)
    year = found.group() if found else ''
    def event(text):
        if year:
            text = re.sub(r'(?<!\d)' + year + r'(?:年)?(?!\d)', '', text)
        return re.sub(r'\s+', ' ', text).strip(' -·()（）')
    translated = (song_zh or '').strip().strip('《》')
    if translated.casefold() == (song or '').strip().casefold():
        translated = ''
    # Preserve complete fields; never silently chop names or change the requested order.
    return ' '.join(x for x in [artist, (song or '').strip(), ' & '.join(aliases), translated,
                                year, event(en), event(zh), '欧美现场 中英字幕 Grammy Billboard'] if x)


def for_post(directory, post):
    """Use concert metadata when present; cached upload JSON uses the same rule."""
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parents[1]
    directory = Path(directory)
    slug = directory.parent.parent.name if directory.parent.name == 'songs' else directory.parent.name
    info_path = root / 'concerts' / slug / 'concert.json'
    song = post.get('song') or {}
    perf = post.get('performance') or {}
    info = json.loads(info_path.read_text()) if info_path.is_file() else {}
    translation = directory / 'title_translation.json'
    chosen = json.loads(translation.read_text()).get('title_zh') if translation.is_file() else None
    return build_title(song.get('artist_zh') or info.get('artist_zh'), song.get('artist') or info.get('artist'),
                       song.get('title_song') or song.get('title'), chosen or song.get('title_zh'),
                       info.get('title_zh') or perf.get('event_zh') or perf.get('event'),
                       info.get('title_en') or perf.get('event_en'), year=perf.get('date') or info.get('date'),
                       nicknames=song.get('nicknames_zh'))
