"""Compare a FIBO master and all four crops with the exact source before release."""
from datetime import datetime
import io
from pathlib import Path

from PIL import Image
from workflow.llm import vision_json
from workflow.live.paths import Concert, read_json, write_json
from workflow.reviewed_cover import digest

CHECKS = ('performer_identity', 'same_people_and_objects', 'natural_face_and_hands',
          'no_source_lettering', 'four_crops_keep_lead', 'titles_and_brand_clear')
REVIEW_POLICY = 'source-pose-and-painterly-style-v3'


def accepted(result):
    """An omitted check or ambiguous response never grants release permission."""
    return (result.get('pass') is True and result.get('defects') == []
            and all(result.get('checks', {}).get(key) is True for key in CHECKS))


def review(directory):
    manifest = directory/'stage.json'
    version = digest(manifest)
    previous = read_json(directory/'visual-review.json', {})
    if previous.get('review_hash') == version and previous.get('review_policy') == REVIEW_POLICY:
        return previous
    staged = read_json(manifest)
    concert = Concert(staged['slug'])
    item = concert.item(staged['name'])
    inputs = [('Original source, authoritative', Path(staged['raw'])),
              ('Generated oil painting', directory/'art.png')]
    inputs += [(v['platform']+' '+v['ratio'], directory/(v['platform']+'-'+v['ratio']+'.jpg'))
               for v in staged['variants']]
    images = []
    for label, path in inputs:
        with Image.open(path) as image:
            image = image.convert('RGB');image.thumbnail((1600, 1600))
            stream = io.BytesIO();image.save(stream, format='JPEG', quality=94)
        images.append((label, stream.getvalue()))
    result = vision_json(
        '你是演唱会封面的视觉质检员。基于原片逐项找有证据的交付问题；仅输出JSON。不能把正常油画笔触、舞台妆容、服装尖刺、道具或演唱表情误判成人体畸形。',
        f'已由原片来源确认：这是{item.get("artist") or concert.load("info").get("artist")}演唱《{item["title"]}》的实际画面。'
        '不要凭造型猜成另一个名人；身份项比较AI与原片是不是同一表演者，不推翻原片来源资料。'
        '原片是唯一事实依据。检查主唱、眼睛、双手、姿态、人数、乐器与舞台。'
        '特别检查暗处或模糊背景被画成原片没有的清晰人脸、乐手、伴舞或乐器；有一处就拒绝。'
        '不得新增眼镜；不得保留原片的转播文字或台标；我们后期添加的歌曲标题、艺人演出署名、左上朝阳Adele及4K徽章应保留且完整。'
        '四比例均须看清主唱，文字不能遮眼口，不能有截断标题、裁掉主角或错误新增人物。'
        '竖版围绕主唱裁切是正常排版，可以裁掉边缘伴舞、乐手或观众；这本身不改变舞台事实。'
        '独唱无需把所有背景人物放入竖版，只要求主唱完整可辨；主要署名合作歌手则应兼顾。'
        '这是油画风格封面，允许可见笔触、纹理、抽象小细节和色彩明暗变化，不要求照片级皮肤或牙齿。'
        '自然演唱时张嘴、舞台表情、长指甲、尖刺手套、骷髅道具属于原片事实，不能当作额外手指或怪物。'
        '仍须逐一比较头部角度、凝视方向、手腕位置、手掌朝向和指尖姿态。把伸展手指改成卷曲、把向外伸的手移到裙上、仰头改成正面，均为真实姿态错误，必须拒绝。'
        '原片被袖口、手套、道具或暗光遮挡的手部不能补成清晰裸手；不能以自然补全或风格化为理由通过这些改变。'
        '五官/双手项仅对有明确对比证据的结构性错误判false，例如多出眼睛、明显错位的鼻口、完全错误手势、原片没有的额外手指；不能只笼统说油画模糊/笔触夸张。'
        '文字可以覆盖服装和躯干；主唱眼睛、嘴巴及核心脸部不可遮挡。被裁掉的边缘伴舞或观众无需完整保留。'
        '拒绝时在每条defect中写清图名、具体位置、原片对应位置与实际差别；仅有猜测不能写成已证实缺陷。'
        '返回 {"pass":布尔,"checks":{'+','.join('"'+k+'":布尔' for k in CHECKS)+'},'
        '"defects":[具体问题],"reason":"逐项核对结论"}。缺少证据或拿不准时pass=false。',
        images, label='封面发布前复核')
    if digest(manifest) != version:
        raise ValueError('Cover changed during visual review')
    record = dict(status='approved' if accepted(result) else 'rejected', review_hash=version,
                  review_policy=REVIEW_POLICY,
                  reviewed_at=datetime.now().astimezone().isoformat(), stage=str(directory),
                  method='vision_model_source_and_four_crops', result=result)
    write_json(directory/'visual-review.json', record)
    return record
