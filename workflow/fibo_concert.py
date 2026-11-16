"""Generate one FIBO master per concert song and register four platform previews."""
import fcntl
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

from workflow.ai_cover import reviewed_revision
from workflow.cover_eye_review import check_for_blink
from workflow.fibo_cover import concert_prompt, PROMPT_VERSION, CLEAN_VERSION

from workflow.live.paths import Concert, ROOT, read_json, write_json
from workflow.local_cover_report import report


def check_group_reference(item, spec, reference):
    """A co-performance needs a visual review of the exact source image."""
    notes = [part.strip() for part in (item.get("notes") or "").split(";")]
    live_notes = [part for part in notes if not re.search(
        r"\b(?:cover|song|elements|remix)\b|\bwith videos? of\b", part, re.I)]
    artist = item.get("artist") or ""
    credits = " ".join([artist, *live_notes])
    group = (spec.get("group_performance") or spec.get("group_review") or item.get("guests")
             or re.search(r"\b(?:with|feat(?:uring)?|ft)\b", credits, re.I) or re.search(r"[&×、]", artist))
    if not group:
        return
    solo = spec.get("solo_review") or {}
    if (solo.get("performer") and solo.get("front_clear") is True and solo.get("reason")
            and solo.get("reference_sha256") == hashlib.sha256(reference).hexdigest()):
        return
    if (not spec.get("group_performance") and not item.get("guests") and not spec.get("group_review")
            and solo.get("reason") and solo.get("reference_sha256") == hashlib.sha256(reference).hexdigest()):
        return
    review = spec.get("group_review") or {}
    performers = {p.strip().casefold() for p in review.get("performers", []) if isinstance(p, str) and p.strip()}
    if len(performers) < 2 or review.get("reference_sha256") != hashlib.sha256(reference).hexdigest():
        raise ValueError(f"{item['name']}: 请复核本曲主唱正面单人镜头或主要表演者同框镜头及竖裁")


def generate_one(concert, item, spec, base, model, worker=None, *, replace_existing=False):
    if worker:
        # Remote inference owns the remote GPU lock, not the primary GPU slot.
        return _generate_one(concert, item, spec, base, model, worker=worker, replace_existing=replace_existing)
    # Shared with audio separation: all callers serialize before loading weights.
    slot = Path.home() / 'Library/Caches/adele/separator.lock'
    slot.parent.mkdir(parents=True, exist_ok=True)
    with slot.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return _generate_one(concert, item, spec, base, model, replace_existing=replace_existing)


def _generate_one(concert, item, spec, base, model, worker=None, *, replace_existing=False):
    name = item['name']
    reviewed = reviewed_revision(concert.song_dir(item) / 'covers/ai')
    if reviewed and not replace_existing:
        return dict(song=name, title=item['title'], artist=item.get('artist'), master=reviewed[0]['file'],
                    review_hash=reviewed[0]['review_hash'], reused=True)
    if spec.get('selection_review') == 'needs_group_reference' and not spec.get('solo_review'):
        raise ValueError(f'{name}: 多人合作曲待重选同台原帧')
    ai = concert.song_dir(item) / 'covers/ai'
    source = ai / spec['reference']
    helmet_args = ['--opaque-helmets'] if spec.get('opaque_helmets') else []
    reference = source.read_bytes()
    pinned = spec.get('reference_lock')
    if pinned and (pinned['source_time'] != spec['source_time']
                   or pinned['reference_sha256'] != hashlib.sha256(reference).hexdigest()):
        raise ValueError(f'{name}: 选帧与已确认的时间码或原片不一致')
    check_group_reference(item, spec, reference)
    check_for_blink(source, spec, 'reference')
    prompt = spec.get('prompt_override') or concert_prompt(spec['scene_note'], bool(helmet_args))
    policy = read_json(concert.dir / "vertical_source.json", {}).get("songs", {}).get(name, {})
    expect_live7 = spec.get("expect_live7", concert.slug == "grammys_2014" and policy.get("kind") == "ts")
    watermark_key = f"{CLEAN_VERSION}:{expect_live7}".encode()
    key = hashlib.sha256(reference + watermark_key + prompt.encode() + json.dumps(spec.get('logo_ellipse')).encode() + PROMPT_VERSION.encode() + model.name.encode()).hexdigest()[:16]
    if spec.get("trim_lower_band"):
        key = hashlib.sha256(f"{key}:trim:{spec['trim_lower_band']}".encode()).hexdigest()[:16]
    if spec.get("logo_boxes"):
        key = hashlib.sha256((key + json.dumps(spec["logo_boxes"])).encode()).hexdigest()[:16]
    if worker:
        key = hashlib.sha256((key + ':remote-fibo-q4-768x432').encode()).hexdigest()[:16]
    if spec.get('face_reference'):
        identity = ai/spec['face_reference']
        key = hashlib.sha256(key.encode()+identity.read_bytes()+str(spec.get('reference_max_area',262144)).encode()+b'composition-detail-v1').hexdigest()[:16]
    parent = base / name / key
    parent.mkdir(parents=True, exist_ok=True)
    from workflow.reviewed_cover import shortlist, stage
    framing = dict(focus=[spec.get('lead_face_x', spec.get('portrait_crop_x', .5)), .34],
                   zoom=1, brand_scale=.70)
    framing.update(spec.get('review_framing') or {})
    raw = ai/spec.get('original_reference', spec['reference'])
    candidates = [dict(source_time=spec['source_time'], frame=str(raw), framing=framing)]
    start, end = policy.get('slice') or spec['source_range']
    samples = read_json(base/'selection'/name/'times.json', [])
    for frame, at in sorted(samples, key=lambda pair: abs(pair[1]-spec['source_time'])):
        if start <= at < end and all(abs(at-c['source_time']) > .05 for c in candidates) and Path(frame).is_file():
            candidates.append(dict(source_time=at, frame=str(frame), framing=framing))
        if len(candidates) == 3:
            break
    for fraction in (.33, .67, .5):
        if len(candidates) == 3:
            break
        at = start+(end-start)*fraction
        if all(at != c['source_time'] for c in candidates):
            candidates.append(dict(source_time=at, framing=framing))
    selection = parent/'selection'
    selection.mkdir(exist_ok=True)
    request_path = selection/'request.json'
    write_json(request_path, dict(slug=concert.slug, name=name, candidates=candidates))
    shortlist(request_path, selection)
    attempts = sorted(parent.glob('attempt-*'))
    folder = attempts[-1] if attempts else None
    if folder and (folder / 'master.metadata.json').exists() and not (folder / 'master.run.json').exists():
        report(folder / 'master.png', folder / 'generate.log', original=source)
    if not folder or not (folder / 'master.run.json').exists():
        folder = parent / f'attempt-{len(attempts)+1:03d}'
        print('GENERATING', name, flush=True)
        logo_args = ['--logo-ellipse', *map(str, spec['logo_ellipse'])] if 'logo_ellipse' in spec else []
        if spec.get("trim_lower_band"):
            logo_args.extend(["--trim-lower-band", str(spec["trim_lower_band"])])
        for box in spec.get("logo_boxes", []):
            logo_args.extend(["--logo-box", *map(str, box)])
        if expect_live7:
            logo_args.append('--expect-live7')
        prompt_args = (['--prompt', prompt] if spec.get('prompt_override') else
                       ['--scene-note', spec['scene_note']])
        worker_args = ['--worker-config', str(worker)] if worker else []
        identity_args = (['--face-reference', str(ai/spec['face_reference']),
                          '--reference-max-area',str(spec.get('reference_max_area',262144))]
                         if spec.get('face_reference') else [])
        subprocess.run([sys.executable, '-m', 'workflow.fibo_cover', str(source), str(folder),
                        '--model', str(model), '--reference-width', '768', *prompt_args, *logo_args, *helmet_args, *worker_args, *identity_args], check=True)
    check_for_blink(folder / 'master.png', spec, 'master')
    # Publishing is a separate action bound to the exact reviewed four crops.
    # An exported AI image alone does not certify the cast, faces or composition.
    review_dir = folder/'cover-review'
    review_dir.mkdir(exist_ok=True)
    request = review_dir/'request.json'
    write_json(request, dict(slug=concert.slug, name=name, source_time=spec['source_time'],
               raw=str(ai/spec.get('original_reference', spec['reference'])),
               run=str(folder), framing=framing))
    review_hash = stage(request, review_dir)
    stats = read_json(folder / 'master.run.json')
    return dict(song=name, title=item['title'], artist=item['artist'], run=str(folder),
                status='awaiting_visual_review', stage=str(review_dir), review_hash=review_hash,
                        generation_seconds=stats['generation_seconds'], elapsed_seconds=stats['elapsed_seconds'],
                        peak_process_gb=round(stats['peak_process_bytes']/1e9, 2))
