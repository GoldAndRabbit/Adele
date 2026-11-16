"""Coordinate song-level local or SSH rendering. Only the coordinator installs products."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from workflow import dual_render
from workflow.delivery_bundle import elapsed_seconds, write_bundle
from workflow.dual_platform import encode_job, sha
from workflow.delivery_config import render_platforms, single_channel_pipeline
from workflow.live.paths import Concert, ROOT, read_json, write_json
from workflow.content_check import require_passed, check_for_render, job_certificate, require_job, require_no_hold,verify_production

VOLUME = Path('/Volumes/harddisk_5T')
PRODUCTS = VOLUME / 'adele-workflow/products'
CACHE = Path.home() / 'Library/Caches/adele'
REMOTE = 'Library/Caches/adele/render-worker'
SSH = ['ssh', '-oBatchMode=yes', '-oIdentitiesOnly=yes', '-oConnectTimeout=10',
       '-oServerAliveInterval=20', '-oServerAliveCountMax=3']


def source_digest(source):
    """Hash each unchanged original once, shared by the two dispatch processes.

    The originals live on a mechanical disk. Rehashing an entire concert for
    every song delays dispatch by minutes and competes with decoding. Reuse a
    digest only while path/device/inode/size/mtime/ctime all match; replacement
    or editing invalidates it. A process lock prevents duplicate full reads.
    """
    def identity():
        stat = source.stat()
        return [str(source.resolve()), stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns, stat.st_ctime_ns]

    version = identity()
    key = hashlib.sha256(json.dumps(version).encode()).hexdigest()
    folder = CACHE / 'source-sha256'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / (key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = folder / (key + '.json')
        cached = read_json(path, {})
        if cached.get('identity') == version and identity() == version:
            return cached['sha256']
        digest = sha(source)
        if identity() != version:
            raise RuntimeError('校验期间原片发生变化，停止当前曲目')
        write_json(path, {'identity': version, 'sha256': digest})
        return digest


@contextmanager
def locked(path, *, shared=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        yield


def worker(folder, source):
    """Run inside one job's directory. Both modes execute this same function."""
    policy = read_json(folder / 'policy.json')
    if not source.is_file():
        raise FileNotFoundError(source)
    certificate = require_job(policy, folder)
    if source_digest(source) != certificate['source_sha256']:
        raise ValueError('原片与内容检查凭据不一致，禁止制作')
    CACHE.mkdir(parents=True, exist_ok=True)
    if CACHE.stat().st_dev != Path('/System/Volumes/Data').stat().st_dev:
        raise RuntimeError('插帧缓存必须在本机内置盘')
    if shutil.disk_usage(CACHE).free < 12 * 1024**3:
        raise RuntimeError('内置盘可用空间低于 12 GiB')
    with tempfile.TemporaryDirectory(dir=CACHE, prefix='interpolate-') as cache:
        encode_job(policy, source, folder, Path(cache), folder)
    manifest = read_json(folder / 'products.json')
    for row in manifest['items']:
        row['sha256'] = sha(folder / row['file'])
    write_json(folder / 'products.json', manifest)


class Remote:
    def __init__(self, host, key, run_id):
        self.host = host
        self.ssh = [*SSH, '-i', str(key.expanduser())]
        self.repo = f'{REMOTE}/runs/{run_id}'
        self.sources = {}

    def command(self, *args, **kwargs):
        return subprocess.run([*self.ssh, '--', self.host, shlex.join(map(str, args))],
                              check=True, **kwargs)

    def sync(self, src, dest, *options):
        subprocess.run(['rsync', '-a', '--partial', '-e', shlex.join(self.ssh),
                        *options, str(src), str(dest)], check=True)

    def setup(self):
        self.command('mkdir', '-p', self.repo, f'{REMOTE}/sources')
        self.command('test', '-x', f'{REMOTE}/venv/bin/python')
        self.sync(str(ROOT / 'workflow') + '/', f'{self.host}:{self.repo}/workflow/',
                  '--exclude=__pycache__', '--include=*/', '--include=*.py', '--include=*.m',
                  '--include=portrait_style.json', '--exclude=*')
        self.command('mkdir', '-p', self.repo + '/assets')
        self.sync(ROOT / 'assets/adele-logo.png', f'{self.host}:{self.repo}/assets/')
        self.sync(ROOT / 'delivery_defaults.json', f'{self.host}:{self.repo}/')

    def render(self, folder, source, digest, log):
        # Verified sources retain their download mtime after rsync. That mtime
        # is not cache recency: count-only eviction repeatedly deleted an older
        # concert being alternated with a newer one. Evict only under pressure.
        cleanup = """from pathlib import Path
import re,sys,shutil
folder=Path.home()/'Library/Caches/adele/render-worker/sources'
files=sorted((p for p in folder.iterdir() if re.fullmatch(r'[0-9a-f]{64}',p.name)),key=lambda p:p.stat().st_mtime,reverse=True)
keep={sys.argv[1]}
total=sum(p.stat().st_size for p in files)
freed=0
for p in reversed(files):
    if total<=48*1024**3 and shutil.disk_usage(folder).free>=24*1024**3:
        break
    if p.name not in keep:
        size=p.stat().st_size
        p.unlink()
        total-=size
        freed+=size
print('副机清理可重建源缓存',round(freed/1024**3,2),'GiB')
"""
        self.command('python3', '-c', cleanup, digest, stdout=log, stderr=subprocess.STDOUT)
        target = f'{REMOTE}/sources/{digest}'
        if target not in self.sources:
            probe = subprocess.run([*self.ssh, self.host, shlex.join(['test','-f',target])])
            if probe.returncode not in (0,1):
                raise RuntimeError(f'副机连接失败，SSH 状态 {probe.returncode}')
            existing = (self.command('shasum','-a','256',target,capture_output=True,text=True)
                        .stdout.split()[0] if probe.returncode == 0 else None)
            if existing != digest:
                print('同步已确认的源视频',source,'至',self.host,file=log,flush=True)
                partial = target + '.' + self.repo.rsplit('/',1)[-1] + '.partial'
                self.sync(source, f'{self.host}:{partial}')
                checksum = self.command('shasum','-a','256',partial,capture_output=True,text=True)
                if checksum.stdout.split()[0] != digest:
                    raise ValueError('副机原片 SHA-256 校验失败')
                self.command('mv',partial,target)
            self.sources[target] = True
        self.command('touch',target)
        job = f'{self.repo}/jobs/{folder.parent.name}'
        self.command('mkdir', '-p', job)
        self.sync(str(folder) + '/', f'{self.host}:{job}/', '--exclude=*.log')
        # The remote command starts in the account home; use absolute job and source paths.
        cmd = (f'export PATH=/opt/homebrew/bin:$PATH; cd "$HOME/{self.repo}" && '
               f'"$HOME/{REMOTE}/venv/bin/python" -u -m workflow.concert_delivery worker '
               f'"$HOME"/{shlex.quote(job)} "$HOME"/{shlex.quote(target)}')
        print('原片 SHA-256 已校验，启动副机制作',file=log,flush=True)
        self.command('caffeinate','-i','sh', '-c', cmd, stdout=log, stderr=subprocess.STDOUT)
        print('副机制作完成，开始回传并核对成品',file=log,flush=True)
        start = time.monotonic()
        self.sync(f'{self.host}:{job}/', str(folder) + '/')
        return round(time.monotonic() - start, 3)


def input_digest(folder, source_digest):
    signature = hashlib.sha256()
    for p in ('policy.json','header.png','portrait.ass','landscape.ass','watermark.json',
              'portrait-mask.png','landscape-mask.png'):
        signature.update((folder / p).read_bytes())
    signature.update(source_digest.encode())
    signature.update((ROOT/'assets/adele-logo.png').read_bytes())
    for p in ('dual_platform.py','dual_render.py','original_master.py','stream_delivery.py','native/apple_interpolate.m','song/render.py'):
        signature.update((ROOT/'workflow'/p).read_bytes())
    return signature.hexdigest()


def run(concert, remote, run_id, only=None, *, single_worker=False, platforms=None):
    if not VOLUME.is_mount():
        raise RuntimeError(f'成品盘未挂载 {VOLUME}')
    state = concert.dir / 'delivery-runs' / run_id
    state.mkdir(parents=True)
    inputs = read_json(concert.dir / 'vertical_source.json')['songs']
    items = concert.song_items()
    if only:
        unknown = set(only) - {item["name"] for item in items}
        if unknown:
            raise ValueError(f"未知曲目 {sorted(unknown)}")
        items = [item for item in items if item["name"] in only]
    hashes = {}
    jobs = []
    preparation = {}
    selected = render_platforms(platforms)
    # Preflight the whole selection before hashing, preparing assets or dispatching.
    reports = {it['name']: check_for_render(concert, it) for it in items}
    for item in items:
        name = item['name']
        preparation[name] = time.monotonic(), datetime.now().astimezone().isoformat()
        d = concert.song_dir(item)
        policy = dict(inputs[name], delivery_platforms=list(selected),
                      single_channel_pipeline=single_channel_pipeline())
        source = Path(policy['source'])
        if source not in hashes:
            print(name, '校验原片 SHA-256（未变更原片复用校验缓存）', flush=True)
            hashes[source] = source_digest(source)
        folder = PRODUCTS / concert.slug / name / run_id
        folder.mkdir(parents=True)
        dual_render.configure(concert, item, folder)
        dual_render.assets()
        shutil.copyfile(d / 'watermark.json', folder / 'watermark.json')
        policy['content_check'] = job_certificate(reports[name], folder, hashes[source])
        write_json(folder / 'policy.json', policy)
        fingerprint = input_digest(folder, hashes[source])
        manifest = read_json(d/'products/products.json', {})
        if (manifest.get('input_digest') == fingerprint and manifest.get('status') == 'ready'
                and {r['platform'] for r in manifest['items'] if (d/'products'/r['file']).is_file()}
                >= set(selected)):
            shutil.rmtree(folder)
            write_bundle(concert,item)
            continue
        jobs.append((item, source, folder, fingerprint))
    workers = 2 if remote and not single_worker else 1

    for i, (item, _, _, _) in enumerate(jobs):
        executor = remote.host if remote and (single_worker or i % 2) else platform.node()
        previous = read_json(concert.song_dir(item)/'render_status.json', {})
        if previous.get('finished_at') and previous.get('run_id'):
            history = state.parent / previous['run_id']
            if history.is_dir():
                write_json(history / (item['name'] + '.json'),
                           {**previous, 'elapsed_seconds': elapsed_seconds(previous)})
        write_json(concert.song_dir(item)/'render_status.json',
                   {'status':'queued', 'run_id':run_id, 'executor':executor})

    def process(index):
        peer = remote if single_worker or index == 1 else None
        if peer and jobs[index::workers]:
            peer.setup()
        for item, source, folder, fingerprint in jobs[index::workers]:
            name = item['name']
            d = concert.song_dir(item)
            logfile = state / (name + '.log')
            record = {'run_id':run_id, 'executor':peer.host if peer else platform.node(),
                      'mode':'ssh' if peer else 'local','log':str(logfile.resolve()),
                      'status':'running','delivery_platforms':list(selected)}
            with locked(d/'render.lock'), logfile.open('a', buffering=1) as log:
                start, record['started_at'] = preparation[name]
                record['preparation_seconds'] = round(time.monotonic() - start, 3)
                write_json(d/'render_status.json',record)
                try:
                    require_no_hold(concert, item)
                    print(record['started_at'], name, record['executor'], '准备制作', file=log)
                    if peer:
                        record['return_seconds'] = peer.render(folder,source,hashes[source],log)
                    else:
                        subprocess.run([sys.executable,'-u','-m','workflow.concert_delivery','worker',
                                        folder,source], cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
                    m = read_json(folder/'products.json')
                    if m['status']!='ready' or {r['platform'] for r in m['items']}!=set(selected):
                        raise ValueError('所选平台成品不完整')
                    check_start = time.monotonic()
                    for row in m['items']:
                        if sha(folder/row['file']) != row['sha256']:
                            raise ValueError('成品 SHA-256 校验失败')
                    record['checksum_seconds'] = round(time.monotonic() - check_start, 3)
                    # Changes made while a long render runs also invalidate delivery.
                    require_no_hold(concert, item)
                    fresh = verify_production(concert, item,reports[name])
                    if fresh['fingerprint'] != reports[name]['fingerprint']:
                        raise ValueError('制作期间边界或字幕变更，保留旧成品，不交付过期结果')
                    m.update(input_digest=fingerprint, production_log=record['log'],run_id=run_id)
                    write_json(folder/'products.json',m)
                    link = d/'products'
                    if link.exists() and not link.is_symlink():
                        raise ValueError(f'保留已有目录 {link}')
                    temp = d/('products.'+run_id)
                    temp.symlink_to(folder)
                    temp.replace(link)
                    record.update(status='ready',render_host=m['render_host'])
                    write_json(d/'render_status.json',record)
                    print('所选平台成品校验完成',list(selected),m['render_host'],file=log)
                    if peer:
                        try:
                            peer.command('rm','-rf',f'{peer.repo}/jobs/{folder.parent.name}')
                        except subprocess.CalledProcessError as exc:
                            print('已交付，副机暂存清理失败',exc,file=log)
                except Exception as exc:
                    record.update(status='failed',error=str(exc))
                    print('失败',repr(exc),file=log)
                finally:
                    record['elapsed_seconds'] = round(time.monotonic() - start, 3)
                    record['finished_at']=datetime.now().astimezone().isoformat()
                    write_json(d/'render_status.json',record)
                    write_json(state / (name + '.json'), record)
                    if record['status'] == 'ready':
                        write_bundle(concert,item)
            print(name,record['status'],flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(process, range(workers)))
    failures=[item['name'] for item,_,_,_ in jobs
              if read_json(concert.song_dir(item)/'render_status.json',{}).get('status')!='ready']
    if failures:
        raise RuntimeError('制作失败 '+', '.join(failures))


def main():
    if sys.argv[1:2] == ['worker']:
        worker(Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
        return
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert')
    parser.add_argument('--only', nargs='+', help='仅制作指定的曲目目录')
    parser.add_argument('--remote',help='SSH user@host; omit for local only')
    parser.add_argument('--key',type=Path,default=Path('~/.ssh/adele_render_worker'))
    parser.add_argument('--single-worker', action='store_true', help='指定机器独立领取一首歌')
    parser.add_argument('--platforms', nargs='+', choices=['bilibili','douyin'], help='覆盖默认制作平台')
    args=parser.parse_args()
    concert=Concert(args.concert)
    if not concert.setlist.is_file():
        parser.error('找不到歌单')
    run_id=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6]
    remote = Remote(args.remote,args.key,run_id) if args.remote else None
    if args.single_worker and (len(args.only or []) != 1 or args.only[0] not in {it['name'] for it in concert.song_items()}):
        parser.error('--single-worker 需指定一首有效曲目')
    with locked(concert.dir/'delivery-runs/queue.lock', shared=args.single_worker):
        if args.single_worker:
            with locked(concert.songs/args.only[0]/'dispatch.lock'):
                run(concert, remote, run_id, args.only, single_worker=True, platforms=args.platforms)
        else:
            run(concert, remote, run_id, args.only, platforms=args.platforms)


if __name__=='__main__':
    main()
