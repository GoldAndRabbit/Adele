"""Browser preview service for the standard workflow and explicit diagnostics."""
import fcntl
from pathlib import Path
from workflow.live.paths import ROOT, CONCERTS, Concert, read_json, write_json
from workflow.vertical_cover import original_source

def visible():
    for folder in sorted(CONCERTS.iterdir()):
        if folder.is_dir():
            concert = Concert(folder.name)
            for item in concert.song_items():
                if not item.get('review_hidden'):
                    yield concert, item

def inventory():
    rows = []
    for c, it in visible():
        d = c.song_dir(it)
        try:
            source = str(original_source(c, it))
        except (FileNotFoundError, KeyError):
            source = None
        captions = any((d/'subs'/n).is_file() for n in ['lyrics_poetic.ass','lyrics_literal.ass','lyrics.ass'])
        ai = d/'covers/ai'
        masters = [m for m in read_json(ai/'masters.json', []) if (ai/m['file']).is_file()]
        prior = list(ai.glob('runs/*/candidate-*.json'))
        rows.append(dict(concert=c.slug, song=it['name'], title=it['title'], source=source,
            subtitles=captions, ai_masters=len(masters), ai_prior_attempts=len(prior),
            browser=(d/'vertical/original-selected.mp4').is_file(),
            status='missing_source' if not source else 'missing_subtitles' if not captions else 'queued',
            link=f'http://127.0.0.1:8160/#/{c.slug}/{it["name"]}'))
    return rows

def enable_browser(c, it):
    """Keep authoritative source choices and reuse their prepared clean clips."""
    from workflow.browser_library import prepare_browser, prepare_preview_crop, source_identity
    d = c.song_dir(it)
    policy = read_json(c.dir/'vertical_source.json', {})
    selected = policy.get('songs', {}).get(it['name'])
    if selected:
        source = original_source(c,it)
        output = Path(selected['directory'])/'source.mp4'
        decoder = selected.get('audio_decoder') or read_json(c.dir/'concert.json', {}).get('audio_decoder')
        expected = source_identity(source, selected['slice'], decoder)
        if not output.is_file() or read_json(output.parent/'source.json') != expected:
            prepare_browser(c,it)
        prepare_preview_crop(d,output)
        from workflow.vertical_source import _publish
        _publish(c,it,output)
        info = read_json(d/'song.json', {})
        info['preview_mode'] = 'browser'
        write_json(d/'song.json',info)
        with (c.dir / '.browser-policy.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            config = read_json(c.dir / 'browser_previews.json', {'songs': []})
            if it['name'] not in config['songs']:
                config['songs'].append(it['name'])
                write_json(c.dir / 'browser_previews.json', config)
    else:
        prepare_browser(c,it)
    from workflow.portrait_browser import preview_data
    preview_data(c,it,d)

def metadata(c,it):
    from workflow.delivery_bundle import write_bundle
    if not read_json(c.song_dir(it)/'post_draft.json', {}):
        raise ValueError('缺少投稿基础资料，不编造标题信息')
    write_bundle(c,it)
