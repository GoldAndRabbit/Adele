"""Deterministic Bilibili title, independent from Douyin metadata."""
import re

NICKNAMES = {"Katy Perry": ("水果姐",), "Taylor Swift": ("霉霉",)}
VERSION = 'bounded-whole-fields-20261107'


def build_title(artist_zh, artist_en, song, song_zh, event_zh, event_en, subs=None, *, year=None, nicknames=None, limit=80):
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
    # Same whole-field fallback policy as Douyin: never slice a name or add ellipses.
    song = (song or '').strip()
    alias = ' & '.join(aliases)
    event_en, event_zh = event(en), event(zh)
    def join(*fields):
        return ' '.join(x for x in fields if x)
    full = join(artist, song, alias, translated, year, event_en, event_zh,
                '欧美现场 中英字幕 Grammy Billboard')
    if limit is None or len(full) <= limit:
        return full
    choices = []
    # Remove optional search keywords and duplicated event languages first.
    for suffix in ['欧美现场 中英字幕 Grammy', '欧美现场 中英字幕', '中英字幕']:
        choices.append(join(artist, song, alias, translated, year, event_en, event_zh, suffix))
    choices += [join(artist, song, alias, translated, year, event_zh, '中英字幕'),
                join(artist, song, translated, year, event_zh, '中英字幕'),
                join(artist, song, year, event_zh, '中英字幕'),
                join(artist, song, translated, year, '中英字幕'),
                join(artist, song, year, '中英字幕')]
    parts = [part.strip() for part in song.split('/') if part.strip()]
    compact_song = parts[0] + f'等{len(parts)}首串烧' if len(parts) > 2 else song
    chinese_artist = re.sub(r'\s*(?:、|，|&|与)\s*', ' & ', (artist_zh or '').strip())
    # Keep all artists in Chinese when that fits better; otherwise explicitly say 等.
    names = re.split(r'\s*&\s*|\s*,\s*|\s+(?:feat\.?|ft\.?)\s+', artist, flags=re.I)
    first = names[0] + ('等' if len(names) > 1 else '')
    for credit in dict.fromkeys([artist, chinese_artist, first]):
        if not credit:
            continue
        for title in dict.fromkeys([compact_song, translated]):
            if not title:
                continue
            choices += [join(credit, title, year, event_zh, '中英字幕'),
                        join(credit, title, year, '中英字幕'), join(credit, title)]
    for choice in choices:
        if choice and len(choice) <= limit:
            return choice
    raise ValueError('无法在保留完整歌名/译名与歌手署名的条件下缩短标题')


def for_post(directory, post, *, limit=80):
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
                       nicknames=song.get('nicknames_zh'), limit=limit)
