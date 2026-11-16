"""Select a new song-local reference after a rejected FIBO composition."""
import io
from pathlib import Path
import shutil

from PIL import Image
from workflow.fibo_library import sample
from workflow.llm import vision_json
from workflow.live.paths import ROOT, read_json, write_json


def reselect(concert, item, *, excluded_times=()):
    path = concert.dir/'fibo-cover-plan.json'
    plans = read_json(path, {})
    previous = plans.get(item['name'], {})
    if any(previous.get(k) for k in ('reference_lock', 'group_review', 'solo_review')):
        raise ValueError('Preserve the explicitly reviewed reference; manual repair required')
    # Twelve coarse frames can miss the lead between dance shots. Rejected
    # songs get the two-second source scan before another inference is spent.
    from workflow.fibo_dense_samples import refine
    refine(concert, item)
    base = ROOT/'work/fibo-batch'/concert.slug
    folder = base/'selection'/item['name']
    # Explicit replacement exclusions survive retries, even after the plan has
    # advanced to a rejected candidate and no longer points at the old release.
    excluded = list(excluded_times)
    if previous.get('source_time') is not None:
        excluded.append(previous['source_time'])
    for manifest in (base/item['name']).glob('*/attempt-*/cover-review/stage.json'):
        if read_json(manifest.parent/'visual-review.json', {}).get('status') == 'rejected':
            excluded.append(read_json(manifest)['source_time'])
    choices = [(i,Path(p),at) for i,(p,at) in enumerate(read_json(folder/'times.json'))
               if not any(abs(at-t)<.05 for t in excluded)]
    if not choices:
        raise ValueError('No untried original reference remains')
    images = []
    for i,p,at in choices:
        with Image.open(p) as raster:
            raster = raster.convert('RGB');raster.thumbnail((960,540))
            stream = io.BytesIO();raster.save(stream,format='JPEG',quality=94)
        images.append((f'index={i}, source_time={at}',stream.getvalue()))
    result = vision_json(
        '为演唱会歌曲选择严格忠于原片的AI封面参考。只能从给出的候选中选择一帧。输出JSON。',
        f'主艺人是{item.get("artist") or concert.load("info").get("artist")}，曲目{item["title"]}。'
        '选择主唱正面或自然侧脸、眼睛自然睁开、神态自然、话筒不挡双眼鼻子、双手姿态清楚的镜头。'
        '优先中近景单人，避免小人远景、背影、闭眼、极度张口、模糊及观众镜头。'
        '此曲先前的油画版本未通过，所以应选择能清楚表达真实背景和人物的新镜头，避免大片不明暗部。'
        '同时检查3:4裁切可保留主唱。输出 {"index":候选编号或null,"scene_note":"仅描述可见事实的英文短句",'
        '"lead_x":主唱脸中心横坐标0至1,"reason":"选择理由"}；没有合适帧则index=null。',
        images,label='封面退回后重新选帧')
    selected = next((row for row in choices if type(result.get('index')) is int and row[0]==result['index']),None)
    if not selected or not result.get('scene_note') or not isinstance(result.get('lead_x'),(float,int)):
        raise ValueError('No usable reference chosen: '+str(result.get('reason')))
    index,source,at = selected
    x = result['lead_x']
    if not 0<=x<=1:
        raise ValueError('Invalid lead position')
    directory = concert.song_dir(item)/'covers/ai'
    ref = directory/'references'/f'performance-{at:.3f}.jpg'
    ref.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,ref)
    policy = read_json(concert.dir/'vertical_source.json')['songs'][item['name']]
    spec = dict(previous,reference=str(ref.relative_to(directory)),original_reference=str(ref.relative_to(directory)),
                source_time=at,source=policy['source'],source_range=policy['slice'],scene_note=result['scene_note'],
                review_framing=dict(focus=[x,.34],portrait_focus=[x,.34],zoom=1,brand_scale=.7),
                selection_result=result)
    spec.pop('eye_review',None)
    spec['prompt_override']='Apply a delicate luminous oil-paint glaze to this exact photograph. '+result['scene_note']+' Keep the source anatomy immutable. Preserve exact facial proportions, smooth natural skin, eyelids, expression and visible hand shapes with very fine restrained brushwork. Preserve motion blur instead of inventing fingers or facial detail. Use broader oil brushwork only on clothing and stage surfaces. Preserve the original people, poses and stage objects at their exact positions, and the actual lighting and background. Leave empty, dark, hazy or blurred regions empty, dark, hazy or blurred. Do not invent people, musicians, instruments, faces or scenery. Remove all lettering and broadcast graphics. Full-bleed unlettered oil painting.'
    if concert.slug=='chappell_lolla_brasil_2026':spec['logo_boxes']=[[0,.015,.14,.23],[.69,.015,1,.15]]
    elif concert.slug=='gaga_coachella_2025':spec['logo_boxes']=[[0,.91,.3,1]]
    spec.pop('face_reference',None)
    from workflow.fibo_identity import add_identity_detail
    spec=add_identity_detail(concert,item,spec)
    plans[item['name']] = spec
    write_json(path,plans)
    write_json(folder/'reselection.json',dict(result,source_time=at,excluded=excluded))
    return spec
