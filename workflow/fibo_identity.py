"""Keep face detail from the same native source frame; never fetch another likeness."""
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image
from workflow.cover_eye_review import inspect_eyes
from workflow.live.paths import read_json,write_json


def add_identity_detail(concert,item,spec):
    directory=concert.song_dir(item)/'covers/ai'
    source=Path(spec['source']);at=spec['source_time']
    identity=dict(source=str(source),mtime=source.stat().st_mtime_ns,bytes=source.stat().st_size,time=at)
    token=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    native=directory/'references'/('native-'+token+'.png')
    if not native.is_file():
        pending=native.with_name(native.stem+'.pending.png')
        subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(at),'-i',str(source),
                        '-frames:v','1','-pix_fmt','rgb24','-compression_level','3','-y',str(pending)],
                       check=True,timeout=120)
        pending.replace(native)
    faces=inspect_eyes(native)
    x=spec.get('review_framing',{}).get('focus',[.5,.34])[0]
    faces=[f for f in faces if f['width']>=.035]
    if not faces:return spec
    face=min(faces,key=lambda f:abs(f['x']+f['width']/2-x))
    if face['check_closed']:
        return spec
    with Image.open(native) as image:
        w,h=image.size;cx=face['x']+face['width']/2;cy=face['y']+face['height']/2
        dx=face['width']*.95;dy=face['height']*.85
        box=(max(0,round((cx-dx)*w)),max(0,round((cy-dy)*h)),
             min(w,round((cx+dx)*w)),min(h,round((cy+dy)*h)))
        detail=image.crop(box);name='identity-'+hashlib.sha256(detail.tobytes()).hexdigest()[:16]+'.png'
        detail.save(directory/'references'/name)
    spec.update(reference=str(native.relative_to(directory)),original_reference=str(native.relative_to(directory)),
                face_reference='references/'+name,reference_max_area=262144)
    identity.update(native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),face_box=box,
                    face_reference=spec['face_reference'])
    write_json(native.with_suffix('.json'),identity)
    spec['prompt_override']=('Make a delicate luminous oil painting of the full wide composition in <image_1>. '
        '<image_2> is ONLY a close detail of the SAME main singer from the SAME frame, not a second person. '
        'Keep the exact wide camera framing, subject size, full costume, pose and all original stage objects from <image_1>. '
        'Do not zoom in to the face. Use <image_2> only to preserve the singer\'s facial identity, eyelids, hair, '
        'expression. Preserve a microphone only if it is actually visible in <image_1>; '
        'never introduce a microphone, instrument or stage equipment absent from the source. '
        'Keep the exact colored stage illumination on the face from <image_1>; '
        'do not recolor the skin or neutralize red or blue light. Keep natural smooth facial anatomy with very fine '
        'restrained brushwork; preserve exact visible hands and motion blur. Use broader luminous strokes only on '
        'clothing and stage surfaces. '+spec['scene_note']+
        ' Leave dark, empty, hazy and blurred background areas dark, empty, hazy and blurred. '
        'No invented people, faces or instruments. Remove all lettering, broadcast logos and borders.')
    return spec
