"""Transport one standard FIBO inference to a bounded-memory Mac worker.

Preprocessing, four-format layout and release remain the normal local workflow.
Only a cleaned reference, public prompt and model arguments leave the host.
Returned files are SHA256 checked before they can enter visual review.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import uuid


def run_inference(config, args, reference, output, log, reference_area=None):
    worker = json.loads(Path(config).read_text())
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
           '-i', str(Path(worker['identity']).expanduser()), worker['host']]
    start = args.index('--image-paths')+1
    end = next((i for i in range(start,len(args)) if args[i].startswith('--')),len(args))
    images = [Path(p) for p in args[start:end]]
    request_hash = hashlib.sha256(json.dumps([args,reference_area]).encode()+b''.join(p.read_bytes() for p in images)).hexdigest()
    marker = output.parent/'remote-transfer.json'
    previous = json.loads(marker.read_text()) if marker.exists() else {}
    if previous.get('request_hash') == request_hash:
        remote = previous['directory']
    else:
        key = uuid.uuid4().hex
        remote = worker['directory'].rstrip('/') + '/jobs/' + key
        marker.write_text(json.dumps(dict(request_hash=request_hash, directory=remote, host=worker['host'])))
    subprocess.run([*ssh, 'mkdir -p ' + shlex.quote(remote)], check=True)
    local = output.parent/'remote-request.json'
    names = ['reference.png']+['identity-'+str(i)+'.png' for i in range(1,len(images))]
    local.write_text(json.dumps({'args':args, 'input_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),
                                'images':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in zip(names,images)},
                                'reference_area':reference_area}))
    scp = ['scp', '-q', '-o', 'BatchMode=yes', '-i', str(Path(worker['identity']).expanduser())]
    for source, name in [*zip(images,names), (local, 'request.json')]:
        subprocess.run([*scp, str(source), worker['host']+':'+remote+'/'+name], check=True)
    command = [worker['directory']+'/venv/bin/python', worker['directory']+'/remote_fibo_worker.py', remote+'/request.json']
    result = subprocess.run([*ssh, shlex.join(command)])
    # Fetch the actual remote time/peak-memory measurements, including failures.
    subprocess.run([*scp, worker['host']+':'+remote+'/generate.log', str(log)], check=True)
    result.check_returncode()
    for name in ['master.png', 'master.metadata.json']:
        subprocess.run([*scp, worker['host']+':'+remote+'/'+name, str(output.parent/name)], check=True)
        actual = hashlib.sha256((output.parent/name).read_bytes()).hexdigest()
        expected = subprocess.check_output([*ssh, 'shasum -a 256 '+shlex.quote(remote+'/'+name)], text=True).split()[0]
        if actual != expected:
            raise ValueError('Remote FIBO return checksum mismatch: '+name)
    meta_path = output.with_suffix('.metadata.json')
    metadata = json.loads(meta_path.read_text())
    metadata['image_paths'] = [str(p.resolve()) for p in images]
    metadata['executor'] = worker['host']
    metadata['quantization_bits'] = 4
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
