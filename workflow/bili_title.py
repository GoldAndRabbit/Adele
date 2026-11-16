"""Deterministic Bilibili title, independent from Douyin metadata."""
import re

if __package__:
    from .artist_nicknames import artist_nicknames
else:
    from artist_nicknames import artist_nicknames

VERSION = 'ordered-space-fields-event-required-20261116'


def event_in_title(title, event):
    """Recognize the same event with the year before or after its name."""
    year_pattern = r'(?<!\d)(?:19|20)\d{2}(?!\d)'
    def parts(value):
        value = str(value or '').casefold()
        years = set(re.findall(year_pattern, value))
        name = re.sub(r'\s+', '', re.sub(year_pattern, '', value))
        return name, years
    title_name, title_years = parts(title)
    event_name, event_years = parts(event)
    return bool(event_name and event_name in title_name and event_years <= title_years)


def posting_artist(song, info):
    """Use the registered Chinese credit when a model repeats the English name.

    Only inherit it for the same performer; a guest or collaboration must keep
    its own credit rather than silently becoming the concert's main artist.
    """
    english = song.get('artist') or info.get('artist') or ''
    chinese = song.get('artist_zh') or ''
    normalized = lambda text: re.sub(r'\s+', ' ', str(text)).strip().casefold()
    if (normalized(english) == normalized(info.get('artist') or '')
            and not re.search(r'[\u3400-\u9fff]', chinese)):
        chinese = info.get('artist_zh') or chinese
    return chinese, english


def build_title(artist_zh, artist_en, song, song_zh, event_zh, event_en, subs=None, *, year=None, nicknames=None, limit=80):
    """Fit whole fields while preserving the performance's identity."""
    def clean(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()
    english_artist = clean(artist_en)
    chinese_artist = clean(artist_zh)
    if english_artist == "Disturbed" and chinese_artist in ("", "Disturbed"):
        chinese_artist = "骚动乐团"
    if chinese_artist == english_artist and not re.search(r"[\u3400-\u9fff]", chinese_artist):
        chinese_artist = ""
    track = clean(song)
    translated = clean(song_zh).strip("《》")
    if translated.casefold() == track.casefold():
        translated = ""
    tracks = [part.strip() for part in track.split(" / ") if part.strip()]
    if len(tracks) > 1:
        track = tracks[0] + "等串烧"
        translations = [part.strip() for part in re.split(r'\s*[/／]\s*', translated) if part.strip()]
        if len(translations) > 1:
            translated = translations[0] + "等串烧"
    artist_separator = r"\s*&\s*|、|，|;|\s+(?:feat\.?|ft\.?)\s+"
    if "&" in english_artist:
        artist_separator += r"|,\s+"
    # An ampersand inside a registered band name is part of that name.
    protected_artist = english_artist.replace('Mumford & Sons', 'Mumford \ue000 Sons')
    english_names = [name.replace('\ue000', '&') for name in re.split(artist_separator, protected_artist, flags=re.I)]
    primary_english = english_names[0].strip()
    if len(english_names) > 1:
        english_artist = primary_english + "等"
        chinese_names = re.split(r"\s*&\s*|、|，|与|和", chinese_artist)
        if chinese_artist:
            chinese_artist = chinese_names[0].strip().removesuffix("等") + "等"
        # Nicknames belong to the displayed lead performer, not every guest.
        nicknames = []
    if (primary_english and not re.search(r"[\u3400-\u9fff]", primary_english)
            and re.search(r"[\u3400-\u9fff]", chinese_artist)):
        chinese_artist = re.sub(r'(?<!\S)' + re.escape(primary_english) + r'(?=\s|等?$)', '', chinese_artist, flags=re.I).strip()
        chinese_artist = re.sub(r'\s+等$', '等', chinese_artist)
    aliases = [name for name in artist_nicknames(english_artist, nicknames)
               if name not in chinese_artist and name not in english_artist]
    events = list(dict.fromkeys(filter(None, [clean(event_en), clean(event_zh)])))
    # A full-show title can already identify the event, e.g. the Chinese
    # Super Bowl title. It need not be appended a second time.
    represented = any(event_in_title(track, event) or event_in_title(translated, event) for event in events)
    event = '' if represented else (events[0] if events else '')
    def fields():
        return list(filter(None, [chinese_artist, track, *aliases, english_artist, translated, event]))
    keywords = ['欧美现场', 'Billboard', 'Grammy', '中英字幕']
    if limit is not None:
        lead = " ".join(filter(None, [chinese_artist, track]))
        if len(lead) > limit:
            raise ValueError("完整歌手署名与首曲歌名超过标题字数限制，请先整理署名")
        # Generic keywords yield first. Then drop nicknames, use an existing
        # shorter event label, and finally omit the translated song as a whole.
        # Never erase the concert/program just to satisfy the character limit.
        while aliases and len(' '.join(fields())) > limit:
            aliases.pop()
        if event and len(' '.join(fields())) > limit:
            event = min(events, key=len)
        if len(' '.join(fields())) > limit and not represented:
            translated = ''
        if len(' '.join(fields())) > limit:
            raise ValueError('完整歌手、歌名与演出信息超过80字符，请提供经核对的演出简称或人工标题')
        while keywords and len(' '.join(fields() + keywords)) > limit:
            keywords.pop()
    return ' '.join(fields() + keywords)


def concert_directory(directory):
    from pathlib import Path
    directory = Path(directory)
    if directory.parent.name == 'songs':
        return directory.parent.parent
    slug = 'singles' if directory.parent.name == 'posts' else directory.parent.name
    return Path(__file__).resolve().parents[1] / 'concerts' / slug


def reviewed_title(directory, *, limit=80):
    import json
    from pathlib import Path
    path = concert_directory(directory) / 'review.json'
    if not path.is_file():
        return None
    entry = json.loads(path.read_text()).get('songs', {}).get(Path(directory).name, {})
    title = entry.get('title')
    if not isinstance(title, str) or not title.strip():
        return None
    if limit is not None and len(title) > limit:
        raise ValueError('人工标题超过80字符，请按完整字段调整后重新审核')
    return title


def for_post(directory, post, *, limit=80):
    """Use concert metadata when present; cached upload JSON uses the same rule."""
    from pathlib import Path
    import json
    directory = Path(directory)
    manual = reviewed_title(directory, limit=limit)
    if manual is not None:
        return manual
    info_path = concert_directory(directory) / 'concert.json'
    song = post.get('song') or {}
    perf = post.get('performance') or {}
    info = json.loads(info_path.read_text()) if info_path.is_file() else {}
    # Repair legacy mixed Chinese/English credits with the registered names
    # already used for this same performance's approved cover credits.
    preferences = info_path.parent / 'vertical_preview.json'
    credits = json.loads(preferences.read_text()) if preferences.is_file() else {}
    registered = credits.get('cover_artist_en', {}).get(directory.name)
    if registered:
        song = {**song, 'artist': registered,
                'artist_zh': credits.get('cover_artist_zh', {}).get(directory.name) or song.get('artist_zh')}
    translation = directory / 'title_translation.json'
    translated_info = json.loads(translation.read_text()) if translation.is_file() else {}
    chosen = translated_info.get('title_zh')
    track = song.get('title') or song.get('title_song')
    if "阿森纳队歌" in (song.get('title_song') or "") and "阿森纳队歌" not in (track or ""):
        track = (track or "") + " 阿森纳队歌"
    artist_zh, artist_en = posting_artist(song, info)
    if (not re.search(r'[\u3400-\u9fff]', song.get('artist_zh') or '')
            and re.search(r'[\u3400-\u9fff]', translated_info.get('artist_zh') or '')):
        artist_zh = translated_info.get('artist_zh') or artist_zh
    if track and " / " in track and translation.is_file():
        artist_zh = translated_info.get('artist_zh') or artist_zh
    return build_title(artist_zh, artist_en,
                       track, chosen or song.get('title_zh'),
                       info.get('title_zh') or perf.get('event_zh') or perf.get('event'),
                       perf['event_en_short'] if 'event_en_short' in perf else (info.get('title_en_short') or info.get('title_en') or perf.get('event_en')), year=perf.get('date') or info.get('date'),
                       nicknames=song.get('nicknames_zh'), limit=limit)

def apply_submission_names(page, directory, post, *, title_override=None):
    """Apply the song's structured names to a new or previously reviewed document."""
    from pathlib import Path
    import json
    song = post.get("song") or {}
    translation = Path(directory) / "title_translation.json"
    chosen = json.loads(translation.read_text()) if translation.is_file() else {}
    track = song.get("title_song") or song.get("title") or chosen.get("title") or ""
    config_path = Path(directory) / "song.json"
    display = json.loads(config_path.read_text()).get("collection_display_name") if config_path.is_file() else None
    zh = (chosen.get("title_zh") or song.get("title_zh") or "").strip().strip("《》")
    if title_override is not None and title_override.strip():
        if len(title_override) > 80:
            raise ValueError('人工标题超过80字符，请按完整字段调整后重新审核')
        page["标题"] = title_override
    else:
        page["标题"] = for_post(directory, post)
    if display:
        page["合集显示名称"] = display
    elif track:
        page.setdefault("合集显示名称", " ".join(dict.fromkeys(filter(None, [track.strip(), zh]))))
    page["标题字符数"] = len(page["标题"])
