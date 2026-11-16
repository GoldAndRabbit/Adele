"""Separate original-audio cut observations; never approve from a concatenated clip."""
from pathlib import Path
from workflow.live.paths import Concert, read_json, write_json
from workflow.content_check import selection
from workflow.content_audio_review import extract, ask

BASE = Path(__file__).parent / 'music-reviews-v4'

def observe(slug, name, edge):
    c = Concert(slug); it = c.item(name); d = c.song_dir(it)
    policy = selection(c, it); a, b = policy['slice']
    evidence = read_json(d/'reports/source_lyrics_evidence.json')
    center = a if edge == 'start' else b
    lo, hi = max(0, center-(90 if edge=='start' else 35)), min(evidence['source_duration'], center+45)
    folder = BASE/slug/name
    folder.mkdir(parents=True, exist_ok=True)
    stem = f'{edge}-{lo:g}-{hi:g}'
    audio, output = folder/(stem+'.wav'), folder/(stem+'.json')
    recipe='source_clock_async1_v2'
    if Path(policy['source']).suffix.lower()=='.ts' and output.exists() and read_json(output).get('audio_recipe')!=recipe:
        archive=folder/'before_audio_clock_fix';archive.mkdir(exist_ok=True)
        for p in [audio,output,output.with_suffix('.response.txt')]:
            if p.exists() and not (archive/p.name).exists():p.rename(archive/p.name)
    if not audio.exists(): extract(policy['source'], lo, hi, audio)
    if output.exists(): return read_json(output)
    full_source=read_json(Path(evidence['bank'])/'transcript.json')
    words = [{'s':round(w['s']-lo,2),'e':round(w['e']-lo,2),'w':w['w']}
             for w in full_source['words'] if lo<=w['s']<=hi]
    units=read_json(d/'subs/translation/result.json')['units']
    sung=[u['orig'] for u in units if u.get('type')=='歌词' and not u.get('dropped')]
    identity_hint=('The target is the FIRST performance at the beginning of this end-window; '
        'a new intro/verse heard later is the NEXT performance, not target. '
        f'Target final caption phrases (identity hints only, not proof): {sung[-2:]}. ' if edge=='end' else
        'The target is the performance whose first vocal follows its intro. '
        f'Target first caption phrases (identity hints only): {sung[:2]}. ')
    prompt = (
      f'Listen to this ONE continuous original concert clip. Target song is {it["title"]}. '
      f'It covers source seconds {lo} to {hi}. Planned {edge} cut is at clip-relative second {center-lo}. '
      'All returned timestamps MUST be clip-relative. Do not treat clip start/end as the planned cut. '
      'Return actual audible events, distinguish previous/target/next performance where audible. '
      'Preserve target instrumental intro/outro and all sung phrases; applause/speech is not a reason to fail. '
      'Use the independent raw-source ASR below only to ground which performance is heard; it can mishear words. '
      +identity_hint+
      'Do not invent lyrics. Do not extrapolate outside supplied audio. '
      'Return JSON {"events":[{"start":0,"end":1,"description":"audible fact","owner":"previous/target/next/crowd/speech/uncertain"}],'
      '"cut_status":"passed/needs_change/uncertain","reason":"specific audible facts at planned cut",'
      '"target_music_start":number_or_null,"target_music_end":number_or_null,'
      '"recommended_cut":number_or_null}. '
      'A recommendation is allowed only when the actual boundary is audible in this clip. '
      f'Independent ASR (relative seconds): {words}')
    result = ask(audio, prompt, output)
    record = read_json(output); record.update(source_span=[lo,hi], planned_cut=center,
        original_source=policy['source'], edge=edge,audio_recipe=recipe)
    write_json(output, record)
    print(slug, name, edge, result, flush=True)
    return record

if __name__ == '__main__':
    import sys
    for edge in ['start','end']: observe(sys.argv[1], sys.argv[2], edge)
