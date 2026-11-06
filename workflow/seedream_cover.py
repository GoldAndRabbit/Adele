"""Explicit, bounded Seedream cover trial; never invoked by page loads.

ARK_API_KEY must be provided in the environment. A plan contains 1–3 candidates,
each with a label and prompt, and a reference path relative to the plan file.
Run: python -m workflow.seedream_cover CONCERT SONG PLAN.json
"""
import argparse
import base64
import hashlib
import io
import os
from pathlib import Path

import requests
from PIL import Image

from workflow.ai_cover import render_variants
from workflow.live.paths import Concert, read_json, write_json

MODEL = 'doubao-seedream-5-0-flash-260915'
ENDPOINT = 'https://ark.cn-beijing.volces.com/api/v3/images/generations'


def generate_trial(concert, item, plan_path, skip_failed=False):
    plan = read_json(plan_path)
    candidates = plan['candidates']
    if not 1 <= len(candidates) <= 3:
        raise ValueError('A trial must contain 1–3 candidates')
    key = os.environ.get('ARK_API_KEY')
    if not key:
        raise ValueError('Set ARK_API_KEY in the environment')
    references = [(plan_path.parent / candidate.get('reference', plan.get('reference', ''))).resolve()
                  for candidate in candidates]
    reference_bytes = [path.read_bytes() for path in references]
    directory = concert.song_dir(item) / 'covers/ai'
    run_id = hashlib.sha256(plan_path.read_bytes() + b''.join(dict.fromkeys(reference_bytes)) + MODEL.encode()).hexdigest()[:12]
    run_dir = directory / 'runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    masters = []
    for index, candidate in enumerate(candidates, 1):
        reference = references[index - 1]
        raw = reference_bytes[index - 1]
        with Image.open(io.BytesIO(raw)) as image:
            mime = Image.MIME[image.format]
        encoded = f'data:{mime};base64,' + base64.b64encode(raw).decode()
        source_time = candidate.get('source_time', plan.get('source_time'))
        output = run_dir / f'candidate-{index}.png'
        record_path = run_dir / f'candidate-{index}.json'
        record = dict(model=MODEL, provider='ark', reference=str(reference),
                      source_time=source_time, prompt=candidate['prompt'],
                      selection_reason=candidate.get('selection_reason'), strategy=plan.get('strategy'),
                      source=plan.get('source'), source_range=plan.get('source_range'),
                      reference_role=candidate.get('reference_role'), composition_distinction=candidate.get('composition_distinction'),
                      label=candidate['label'], status='requesting', size='2560x1440')
        if not output.exists():
            prior = read_json(record_path, {})
            if skip_failed and prior.get('status') in {'requesting', 'failed'}:
                print(f'Skipped previous failed/uncertain candidate {index}', flush=True)
                continue
            if prior.get('status') in {'requesting', 'failed'}:
                raise RuntimeError(f'Inspect uncertain previous request before retrying: {record_path}')
            write_json(record_path, record)
            try:
                response = requests.post(ENDPOINT, headers={'Authorization': f'Bearer {key}'},
                    json=dict(model=MODEL, prompt=candidate['prompt'], image=encoded,
                              size='2560x1440', response_format='url', watermark=False,
                              stream=False), timeout=(15, 240))
                if not response.ok:
                    # Do not expose provider responses, which may echo request data.
                    record['http_status'] = response.status_code
                    try:
                        code = response.json().get('error', {}).get('code', '')
                        record['provider_error_code'] = ''.join(c for c in str(code)[:120] if c.isalnum() or c in '._-')
                    except ValueError:
                        pass
                    raise RuntimeError(f'Seedream HTTP {response.status_code}')
                data = response.json()
                result = data['data'][0]
                download = requests.get(result['url'], timeout=(15, 120))
                download.raise_for_status()
                with Image.open(io.BytesIO(download.content)) as image:
                    image.convert('RGB').save(output)
                record.update(status='complete', usage=data.get('usage'),
                              request_id=response.headers.get('x-request-id'),
                              returned_model=data.get('model'))
                write_json(record_path, record)
            except Exception as error:
                record.update(status='failed', error_type=type(error).__name__)
                write_json(record_path, record)
                raise RuntimeError(f'Candidate {index} failed; inspect {record_path}') from None
        rows = render_variants(concert, item, output, candidate['label'])
        masters.append(dict(file=rows[0]['master'], label=candidate['label'],
                            provider='ark', model=MODEL, source_time=source_time,
                            reference='references/' + reference.name, run=run_id))
        print(f"Ready {index}/{len(candidates)}: {candidate['label']}", flush=True)
    # Explicit partial continuation can publish only completed candidates.
    if masters:
        previous = read_json(directory / 'masters.json', [])
        current_files = {row['file'] for row in masters}
        write_json(directory / 'masters.json', [row for row in previous if row.get('file') not in current_files] + masters)
    return masters


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert')
    parser.add_argument('song')
    parser.add_argument('plan', type=Path)
    parser.add_argument('--skip-failed', action='store_true', help='Continue unattempted candidates without retrying previous failures')
    args = parser.parse_args()
    concert = Concert(args.concert)
    generate_trial(concert, concert.item(args.song), args.plan, skip_failed=args.skip_failed)
