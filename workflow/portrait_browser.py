"""Browser portrait preview data: no video rendering or encoding."""
from workflow.live.paths import read_json
import re
from pathlib import Path
from workflow.song.title_translation import header_translation
from workflow.vertical_cover import header_labels


def artist_line(labels):
    separator = r"\s+&\s+|\s+(?:feat(?:uring)?|ft)\.?\s+"
    en, zh = (re.split(separator, labels[key], flags=re.I) for key in ("en", "zh"))
    multiple = len(en) > 1 and (len(zh) > 1 or re.search(r"\b(?:feat(?:uring)?|ft)\.?\s", labels["en"], re.I))
    def bilingual(english, chinese):
        normalize = lambda name: re.sub(r"[‐‑–—]", "-", name).casefold().strip()
        chinese_name = re.sub(r"\s*(?:组合|乐队|乐团)\s*$", "", chinese)
        if not chinese or normalize(english) == normalize(chinese_name):
            return english
        return f"{english} {chinese}"

    if multiple and len(en) > 2:
        return bilingual(en[0], zh[0]) + " 等"
    if multiple and len(en) == len(zh) == 2:
        return " & ".join(bilingual(e, z) for e, z in zip(en, zh))
    return bilingual(labels["en"], labels["zh"])


def preview_data(concert, item, directory):
    labels = header_labels(concert, item)
    info = read_json(directory / 'song.json', {})
    style = read_json(Path(__file__).with_name('portrait_style.json'))
    draft_song = read_json(directory / 'post_draft.json', {}).get('song', {})
    title = info.get('title_song') or item['title']
    text = {'song': title, 'song_zh': header_translation(directory, title, draft_song),
            'en': artist_line(labels), 'event': labels['event']}
    settings = read_json(concert.dir / 'vertical_preview.json', {})
    crop = read_json(directory / 'vertical' / 'preview_crop.json', {}).get('box')
    return {'preview_crop': crop, 'style': style, 'header_text': text,
            'horizontal_caption_band': style.get('horizontal_caption_band', False) or item['name'] in settings.get('horizontal_caption_band', []),
            'portrait_soft_lower_edge': style.get('portrait_soft_lower_edge', False) or item['name'] in settings.get('portrait_soft_lower_edge', []),
            'box': crop or read_json(directory / 'content_box.json', {'x': 0, 'y': 0, 'w': 1, 'h': 1})}
