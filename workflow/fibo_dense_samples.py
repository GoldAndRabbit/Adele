"""Expand difficult songs to a two-second source scan before choosing a cover."""
import argparse
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw
from workflow.cover_eye_review import inspect_eyes
from workflow.fibo_library import BASE, sample
from workflow.live.paths import Concert, read_json, write_json


def refine(concert, item):
    sample(concert, item)
    folder = BASE/concert.slug/'selection'/item['name']
    dense = folder/'dense';dense.mkdir(exist_ok=True)
    policy = read_json(concert.dir/'vertical_source.json')['songs'][item['name']]
    source = Path(policy['directory'])/'source.mp4'
    if not source.is_file():
        raise ValueError('Prepare the correct browser source before dense selection')
    marker = dict(source=str(source),mtime=source.stat().st_mtime_ns,slice=policy['slice'],step=2)
    if read_json(dense/'source.json',{}) != marker:
        # showinfo retains each selected frame's real timestamp. It does not
        # infer timestamps from a rounded fps or from the JPEG sequence number.
        args=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-ss','2','-i',str(source),
              '-an','-vf',"select='isnan(prev_selected_t)+gte(t-prev_selected_t,2)',scale=1280:-2,showinfo",
              '-fps_mode','vfr','-threads','2','-q:v','2','-y',str(dense/'frame-%04d.jpg')]
        result=subprocess.run(args,capture_output=True,text=True,check=True,timeout=600)
        (dense/'extract.log').write_text(result.stderr)
        times=[float(x) for x in re.findall(r'\bn:\s*\d+\s+pts:\s*[-\d]+\s+pts_time:([-\d.]+)',result.stderr)]
        files=sorted(dense.glob('frame-*.jpg'))[:len(times)]
        if len(files)!=len(times) or not times:
            raise ValueError('Dense source timestamps do not match extracted frames')
        rows=[]
        for p,t in zip(files,times):
            at=round(policy['slice'][0]+2+t,3)
            if not policy['slice'][0]<=at<policy['slice'][1]:continue
            faces=inspect_eyes(p)
            lead=faces[0] if faces else {}
            opened=not any(f['check_closed'] for f in faces)
            aperture=min(lead.get('left_eye') or 0,lead.get('right_eye') or 0)
            score=lead.get('width',0)*8+min(aperture,.4)+(1 if opened else -3)
            rows.append(dict(file=str(p),source_time=at,faces=faces,score=score))
        write_json(dense/'ranked.json',rows);write_json(dense/'source.json',marker)
    rows=read_json(dense/'ranked.json');selected=[]
    # Prefer identifiable open-eyed faces. The vision selector still checks
    # identity, so a large dancer's face never automatically becomes the lead.
    for row in sorted(rows,key=lambda r:r['score'],reverse=True):
        if not row['faces'] or row['faces'][0]['width']<.055:continue
        if any(f['check_closed'] for f in row['faces']):continue
        if all(abs(row['source_time']-x['source_time'])>=2.5 for x in selected):selected.append(row)
        if len(selected)==24:break
    if len(selected)<3:
        raise ValueError('Dense scan has too few clear, open-eyed source candidates')
    selected.sort(key=lambda r:r['source_time'])
    sheet=Image.new('RGB',(960,155*math.ceil(len(selected)/4)),'#191c24');draw=ImageDraw.Draw(sheet)
    for i,r in enumerate(selected):
        with Image.open(r['file']) as raster:
            raster.thumbnail((239,134));sheet.paste(raster,(i%4*240,i//4*155))
        draw.text((i%4*240+4,i//4*155+136),f"{i} {r['source_time']:.3f}",fill='white')
    sheet.save(folder/'frames.jpg',quality=95)
    write_json(folder/'times.json',[(r['file'],r['source_time']) for r in selected])
    return len(selected)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert');parser.add_argument('songs',nargs='+');args=parser.parse_args()
    c=Concert(args.concert)
    for name in args.songs:
        print('DENSE_SCAN',name,refine(c,c.item(name)),flush=True)
