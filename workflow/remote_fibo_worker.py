"""Run one requested FIBO inference on a Mac worker; no project secrets needed."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    request = Path(sys.argv[1]).resolve()
    job = json.loads(request.read_text())
    if hashlib.sha256((request.parent/'reference.png').read_bytes()).hexdigest() != job['input_sha256']:
        raise ValueError('Transferred FIBO reference checksum mismatch')
    for name, expected in job.get('images', {}).items():
        if Path(name).name != name or hashlib.sha256((request.parent/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Transferred FIBO auxiliary reference checksum mismatch')
    base = Path.home() / 'Library/Caches/adele/fibo-worker'
    # Share the existing audio worker lock: one heavy job on this Mac in total.
    slot = Path.home() / 'Library/Caches/adele/separator.lock'
    slot.parent.mkdir(parents=True, exist_ok=True)
    with slot.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = request.parent/'success.json'
        if receipt.exists():
            hashes = json.loads(receipt.read_text())
            if all(hashlib.sha256((request.parent/name).read_bytes()).hexdigest() == value
                   for name, value in hashes.items()):
                return
        argv = list(job['args'])
        start = argv.index('--image-paths')+1
        end = next((i for i in range(start,len(argv)) if argv[i].startswith('--')),len(argv))
        argv[start:end] = [str(request.parent/name) for name in (job.get('images') or {'reference.png':None})]
        for flag, value in [('--model', base/'model-q4'),
                            ('--image-paths', request.parent/'reference.png'),
                            ('--output', request.parent/'master.png'),
                            ('--width', '768'), ('--height', '432')]:
            argv[argv.index(flag)+1] = str(value)
        argv.extend(['--quantize', '4'])
        env = dict(os.environ, HF_HUB_OFFLINE='1', TOKENIZERS_PARALLELISM='false',
                   FIBO_PRELOAD_DEVICE='cpu', MLX_MAX_OPS_PER_BUFFER='4',
                   MLX_MAX_MB_PER_BUFFER='16')
        if job.get('reference_area'):
            if job['reference_area'] not in [262144,524288,1048576]:
                raise ValueError('Unsupported conditioning pixel budget')
            env['FIBO_REFERENCE_AREA'] = str(job['reference_area'])
        command = ['/usr/bin/time', '-l', str(base/'venv/bin/python'),
                   str(base/'local_fibo_generate.py'), *argv]
        with (request.parent/'generate.log').open('w') as stream:
            subprocess.run(command, env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        receipt.write_text(json.dumps({name:hashlib.sha256((request.parent/name).read_bytes()).hexdigest()
                                      for name in ['master.png', 'master.metadata.json']}))


if __name__ == '__main__':
    main()
