"""Finish the current cover library before starting the specified delivery set."""
import argparse
import fcntl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image
from workflow.cover_eye_review import inspect_eyes
from workflow.fibo_library import BASE, Concert, current_previews, read_json, render, verify_ui, write_json
from workflow.delivery_bundle import write_bundle
from workflow.ai_cover import reviewed_revision
from workflow.delivery_config import products_ready


def nearby_reference(c, item):
    """Find the same solo shot around the approved timestamp with visible open eyes."""
    plan_path = c.dir / 'fibo-cover-plan.json'
    plans = read_json(plan_path)
    name = item['name']
    spec = plans[name]
    if spec.get('reference_lock') or spec.get('group_review') or spec.get('solo_review'):
        return False
    policy = read_json(c.dir/'vertical_source.json', {}).get('songs', {}).get(name)
    if not policy:
        return False
    start, end = policy['slice']
    ai = c.song_dir(item)/'covers/ai'
    ref = ai/spec['reference']
    faces = inspect_eyes(ref)
    if not faces:
        return False
    lead = faces[0]
    def thumbnail(path):
        with Image.open(path) as im:
            return np.asarray(im.convert('RGB').resize((80,45)), dtype=float)
    original = thumbnail(ref)
    tried = set(spec.get('blink_retry_times', [])) | {spec['source_time']}
    anchor = spec.get('blink_retry_anchor', spec['source_time'])
    first = max(start, anchor-5)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        source=Path(policy['source'])
        clip=Path(policy['directory'])/'source.mp4'
        marker=read_json(clip.parent/'source.json',{})
        seek=first
        if clip.is_file() and marker.get('source')==str(source) and marker.get('slice')==policy['slice'] and marker.get('mtime')==source.stat().st_mtime_ns:
            source=clip
            seek-=start
        subprocess.run(['ffmpeg','-v','error','-ss',str(seek),'-i',str(source),'-t',str(min(end,anchor+5)-first),
                        '-vf','fps=6,scale=1280:-2,format=yuvj420p','-q:v','2',str(folder/'%04d.jpg')], check=True)
        choices = []
        for i, path in enumerate(sorted(folder.glob('*.jpg'))):
            at = round(first+(i+.5)/6,3)
            if min(abs(at-t) for t in tried)<.14:
                continue
            diff = np.abs(thumbnail(path)-original).mean()/255
            if diff > .105:
                continue
            fs = inspect_eyes(path)
            if not fs or any(f['check_closed'] for f in fs):
                continue
            f = fs[0]
            aperture = min(f['left_eye'] or 0, f['right_eye'] or 0)
            if aperture < .18 or abs(f['x']-lead['x'])>.13 or abs(f['y']-lead['y'])>.15 or not .72 < f['width']/lead['width'] < 1.4:
                continue
            choices.append((aperture-diff-abs(at-anchor)*.004, at, path))
        if not choices:
            return False
        _, at, path = max(choices)
        dst = ai/'references'/f'performance-{at:.3f}.jpg'
        dst.write_bytes(path.read_bytes())
    spec.update(source_time=at, reference=str(dst.relative_to(ai)), blink_retry_times=sorted(tried), blink_retry_anchor=anchor)
    write_json(plan_path,plans)
    return True


def stop_if_paused():
    if (BASE / 'PAUSED').exists():
        print('队列已暂停', flush=True)
        raise SystemExit(0)


def cover_stage(model):
    stop_if_paused()
    url='http://127.0.0.1:8160'
    with (BASE/'sidebar-render.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        groups=read_json(BASE/'sidebar.json')
        unresolved=[]
        for group in groups:
            slug=group['slug']
            c=Concert('singles' if slug.startswith('artist_') or slug=='super_bowl_halftime' else slug)
            state_file=BASE/c.slug/'sidebar-render.json'
            states=read_json(state_file,{})
            for track in group['tracks']:
                stop_if_paused()
                name=track['name']
                item=c.item(name)
                if states.get(name)!='verified' or not current_previews(c,item):
                    for attempt in range(4):
                        stop_if_paused()
                        try:
                            states[name]=render(c,item,model,url,slug)
                            break
                        except Exception as exc:
                            states[name]=f'error: {exc}'
                            if '疑似闭眼' not in str(exc) or attempt==3:
                                break
                            try:
                                if not nearby_reference(c,item):
                                    break
                            except (OSError, ValueError, subprocess.SubprocessError) as retry_error:
                                states[name] += f'；重选失败：{retry_error}'
                                break
                    write_json(state_file,states)
                if states.get(name)!='verified' or not current_previews(c,item):
                    unresolved.append([slug,name,states.get(name)])
                    continue
                ai=c.song_dir(item)/'covers/ai'
                reviewed = reviewed_revision(ai)
                if reviewed:
                    verify_ui(url, slug, name, reviewed[0]['file'])
                    continue
                plan=read_json(c.dir/'fibo-cover-plan.json')[name]
                master=next(m for m in read_json(ai/'masters.json') if m.get('provider')=='local' and m.get('source_time')==plan['source_time'])
                verify_ui(url,slug,name,master['file'])
        write_json(BASE/'4k-cover-blockers.json',unresolved)
        return not unresolved


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    args=p.parse_args()
    with (BASE/'4k-delivery.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while not cover_stage(args.model):
            print('等待所列封面修正',flush=True)
            time.sleep(60)
        print('全部封面已验证，开始所选平台成片',flush=True)
        state_file=BASE/'4k-delivery-state.json'
        states=read_json(state_file,{})
        for row in read_json(BASE/'4k-delivery-queue.json'):
            stop_if_paused()
            c=Concert(row['concert']);name=row['song'];item=c.item(name)
            directory=c.song_dir(item);key=c.slug+'/'+name
            try:
                if not products_ready(directory):
                    subprocess.run([sys.executable,'-m','workflow.dual_platform',c.slug,name],check=True)
                else:
                    write_bundle(c,item)
                states[key]='ready'
            except Exception as exc:
                states[key]=str(exc)
            write_json(state_file,states)
            print(key,states[key],flush=True)

if __name__=='__main__':
    main()
