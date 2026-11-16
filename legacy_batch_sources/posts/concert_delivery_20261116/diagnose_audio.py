"""Inspect concrete reported disagreements; keep observations separate from approvals."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from workflow.live.paths import Concert, read_json, write_json
from workflow.content_check import selection
from posts.concert_delivery_20261116.audio_review import extract, ask

BASE = Path(__file__).parent / 'diagnosis-audio'
CASES = [
    ('chappell_reading_2025', '06_casual', 1070, 1135),
    ('chappell_lowlands_2025', '05_guilty_pleasure', 1215, 1280),
    ('chappell_reading_2025', '15_good_luck_babe', 2775, 2830),
    ('chappell_reading_2025', '03_after_midnight', 590, 610),
]

def one(case):
    slug, name, start, end = case
    c = Concert(slug)
    source = selection(c, c.item(name))['source']
    folder = BASE / slug / name
    folder.mkdir(parents=True, exist_ok=True)
    audio, output = folder/'original.wav', folder/'observation.json'
    if not audio.exists():
        extract(source, start, end, audio)
    if output.exists():
        return read_json(output)
    result = ask(audio,
        'Listen only to the supplied ORIGINAL audio. Do not fill in studio lyrics '
        'or use any assumed song title. Transcribe the actual sung and spoken '
        'words with timestamps relative to this clip. Also give audible events '
        'such as music intro, singing starts/stops, applause and transitions. '
        'If unclear mark uncertain. Return JSON {"sentences":[{"start":0.0,'
        '"end":1.0,"text":"actual words","type":"singing/speech"}],'
        '"events":[{"start":0.0,"end":1.0,"description":"heard event"}]}.'
        f' This clip represents original-video seconds {start} through {end}; '
        'timestamps in your response must be relative to the clip, not the original.',
        output)
    write_json(folder/'original-range.json', {'source':source,'span':[start,end],
        'machine_observations_only':True,'human_review':False})
    print(slug, name, result, flush=True)
    return result

if __name__ == '__main__':
    # These are API observations, not concurrent render/separation workers.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, CASES))
