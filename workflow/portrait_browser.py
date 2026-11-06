"""Browser portrait preview data: no video rendering or encoding."""
from workflow.live.paths import read_json
from pathlib import Path
from workflow.vertical_cover import header_labels


def preview_data(concert, item, directory):
    labels = header_labels(concert, item)
    info = read_json(directory / 'song.json', {})
    style = read_json(Path(__file__).with_name('portrait_style.json'))
    translation = read_json(directory / 'title_translation.json', {}).get('title_zh')
    draft_song = read_json(directory / 'post_draft.json', {}).get('song', {})
    translation = translation or draft_song.get('title_zh')
    text = {'song': info.get('title_song') or item['title'], 'song_zh': translation or '',
            'en': labels['en'], 'event': labels['event']}
    settings = read_json(concert.dir / 'vertical_preview.json', {})
    return {'style': style, 'header_text': text,
            'horizontal_caption_band': style.get('horizontal_caption_band', False) or item['name'] in settings.get('horizontal_caption_band', []),
            'portrait_soft_lower_edge': style.get('portrait_soft_lower_edge', False) or item['name'] in settings.get('portrait_soft_lower_edge', []),
            'box': read_json(directory / 'content_box.json', {'x': 0, 'y': 0, 'w': 1, 'h': 1})}
