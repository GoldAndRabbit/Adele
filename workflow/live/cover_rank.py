"""候选封面排序：算法推荐 Top3，其余按分数往下排。结果写 covers/rank.json，审核页按它分组显示。

两部分打分（方案见 docs/design/cover_ranking.md）：
  - 技术分（本地，OpenCV YuNet，不调接口）：在不带字的高清帧 frame_*.jpg 上找主唱的脸，量
      脸大小、脸部清晰度（本首内按百分位比）、脸部亮度、正脸程度、脸有没有贴边被切；
      再拿成品封面和高清帧对比找出标题 / 副标题的笔画，算眼睛 / 整张脸被字盖住多少（16:9 和 4:3 分开算），
      以及 4:3 的裁切窗口有没有把脸裁掉。
  - 观感分（Qwen 看成品 16:9 封面，一首歌一次调用）：按 YouTube / B 站缩略图的标准，
      看眼睛、表情、清晰、字有没有挡脸、构图、整体吸引力，每张给分和一句理由。
  最终分 = 0.55 × 观感 + 0.45 × 技术，闭眼 / 字盖住眼睛（程序测，不让模型判断）再打折；Top3 互相隔开 4 秒以上（不要三张同一个镜头）。

用法：python -m workflow.live.cover_rank <concert_slug> [歌名 ...] [--force] [--no-vlm]
"""
import argparse
import io
import time

import numpy as np
from PIL import Image

from .package import COVER_RE, FRAME_RE
from .paths import Concert, read_json, write_json

VERSION = 2   # 2：字挡脸只用程序测量，不让模型判断
W_VLM, W_TECH = 0.55, 0.45
TOP_GAP = 4.0   # Top3 之间至少隔几秒（同一个镜头的几张只进一张）
VLM_SIZE = (768, 432)

VLM_SYSTEM = ("你是 YouTube 和 B 站音乐频道的封面编辑，负责从候选缩略图里挑点击率最高的封面。"
              "观众在手机信息流里只看到很小的缩略图：要一眼认出歌手、脸清楚、眼睛睁开、表情有感染力。"
              "只按图里看得到的评判，不要编造。输出 JSON。")
VLM_PROMPT = """上面 {n} 张是同一首歌现场演出的候选封面（已经排好标题字），编号见每张图前面的文字。
逐张评分（1~10 分，10 最好），输出 JSON：
{{"items": [{{"id": "图前面的编号", "eyes": "open / half / closed / unseen", "expression": 表情和演唱状态的感染力,
  "clarity": 主唱脸部清晰度（糊、拖影、过曝、太暗扣分）,
  "composition": 构图（主唱是否突出、画面干净、不是背影或被话筒/手/他人挡脸）, "overall": 作为封面的综合分,
  "reason": "一句话（15 字以内）说最主要的优点或问题"}}],
 "top3": ["你认为最好的三张编号，按好到差"]}}
注意：嘴型张开在唱歌是正常的；闭眼、半闭眼、眼神涣散、表情扭曲、脸被挡、模糊要明显扣分。
标题字挡没挡脸由程序另外精确测量，你不用判断，打分时忽略标题字，只看画面本身。"""


def _faces(det, img):
    """YuNet：返回 [(x, y, w, h, 置信度, 右眼xy, 左眼xy, 鼻xy)]，坐标在 960×540 上。"""
    a = np.asarray(img.convert("RGB").resize((960, 540)))[:, :, ::-1].copy()
    det.setInputSize((960, 540))
    _, faces = det.detect(a)
    return [f for f in (faces if faces is not None else []) if f[14] >= 0.8], a


def _glyph_mask(cover, frame):
    """成品封面上标题 / 副标题的笔画（含描边）：封面纯白（字）或近黑描边、而高清帧同一位置不是。只看徽章以下。"""
    import cv2
    c = np.asarray(cover.convert("RGB").resize((960, 540)), dtype=np.int16)
    f = np.asarray(frame.convert("RGB").resize((960, 540)), dtype=np.int16)
    white = (c.min(axis=2) >= 240) & (f.min(axis=2) < 225)
    dark = (c.max(axis=2) <= 32) & (f.max(axis=2) > 70)
    m = (white | dark).astype(np.uint8)
    m[: int(540 * 0.30)] = 0   # logo / 4K 徽章
    return cv2.dilate(m, np.ones((5, 5), np.uint8)) > 0


def _cover_frac(mask, x0, y0, x1, y1):
    x0, y0, x1, y1 = (int(max(0, v)) for v in (x0, y0, x1, y1))
    x1, y1 = min(x1, mask.shape[1]), min(y1, mask.shape[0])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(mask[y0:y1, x0:x1].mean())


def _eye_boxes(f):
    """两只眼睛各一个小框（以五点关键点为中心，宽 ±0.22、高 ±0.12 个眼距）。用脸高算的话，大特写的框会大到碰上标题。"""
    rex, rey, lex, ley = (float(v) for v in f[4:8])
    d = max(8.0, abs(lex - rex))
    return [(ex - 0.22 * d, ey - 0.12 * d, ex + 0.22 * d, ey + 0.12 * d) for ex, ey in ((rex, rey), (lex, ley))]


def _eyes_cover(mask, f, dx=0.0, sx=1.0):
    """眼睛框被字盖住的比例（两只眼取平均）；dx / sx 把 16:9 坐标换到 4:3 掩码上。"""
    return float(np.mean([_cover_frac(mask, (x0 - dx) * sx, y0, (x1 - dx) * sx, y1) for x0, y0, x1, y1 in _eye_boxes(f)]))


def tech_metrics(cdir, cid, frame_file, det):
    """一张候选的技术指标（不含本首内的相对清晰度，那个在 rank() 里按百分位算）。"""
    import cv2
    import make_cover
    frame = Image.open(cdir / frame_file).convert("RGB")
    faces, bgr = _faces(det, frame)
    faces = [f for f in faces if f[3] / 540 >= 0.05]   # 太小的脸（远景里的人）不算
    m = {"faces": len(faces)}
    if not faces:
        return m
    c16 = cdir / f"{cid}.jpg"
    mk16 = _glyph_mask(Image.open(c16), frame) if c16.exists() else None
    # 主唱的脸：画面里可能还有大屏上投出来的大脸（Liability），常常正好在字后面。
    # 取「大、正、没被字挡」的那张：只要主唱的脸露在字外面，这张封面就成立
    fw = {2: 1.0, 1: 0.75, 0: 0.45}
    f = max(faces, key=lambda f: float(f[3]) * fw[make_cover.frontality(f)]
            * (1 - (_eyes_cover(mk16, f) if mk16 is not None else 0.0)))
    x, y, w, h = (float(v) for v in f[:4])
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    roi = g[int(max(0, y)): int(min(540, y + h)), int(max(0, x)): int(min(960, x + w))]
    m.update({
        "face_h": round(h / 540, 3),
        "sharp": round(float(cv2.Laplacian(roi, cv2.CV_32F).var()) * h / 540, 2) if roi.size >= 100 else 0.0,
        "bright": round(float(roi.mean()), 1) if roi.size else 0.0,
        "frontal": make_cover.frontality(f),
        "edge": bool(x < 4 or y < 4 or x + w > 956 or y + h > 536),
        "face_cy": round((y + h / 2) / 540, 3),
    })
    if mk16 is not None:
        m["occ_eyes"] = round(_eyes_cover(mk16, f), 3)
        m["occ_face"] = round(_cover_frac(mk16, x, y, x + w, y + h), 3)
    c43 = cdir / f"{cid}_4x3.jpg"
    if c43.exists():
        cx, cw = make_cover.crop_window(frame, 4 / 3)
        s = 960 / frame.width
        mk = _glyph_mask(Image.open(c43), frame.crop((cx, 0, cx + cw, frame.height)))  # 960×540，横向拉伸过
        m["occ_eyes_43"] = round(_eyes_cover(mk, f, dx=cx * s, sx=960 / (cw * s)), 3)
        m["in_43"] = round(max(0.0, min(x + w, (cx + cw) * s) - max(x, cx * s)) / max(w, 1), 3)
    return m


def tech_score(m, sharp_pct):
    """0~1。没检测到脸给 0.15（背影 / 侧脸 / 全景，一般不适合当缩略图）。"""
    if not m.get("faces"):
        return 0.15
    s = {2: 1.0, 1: 0.75, 0: 0.45}[m["frontal"]]
    s *= 0.5 + 0.5 * min(1.0, m["face_h"] / 0.30)            # 脸越大越好，脸高 30% 封顶
    s *= 0.4 + 0.6 * sharp_pct                                 # 本首里的清晰度百分位
    b = m["bright"]
    s *= 1.0 if 70 <= b <= 215 else 0.75 if 50 <= b <= 235 else 0.5
    s *= 0.8 if m["edge"] and m["face_h"] < 0.5 else 1.0   # 大特写本来就会顶到画面边
    # 字盖住眼睛：擦到一点边（< 10%）不算
    s *= 1 - min(0.7, 2.0 * max(0.0, m.get("occ_eyes", 0) - 0.1)) - min(0.2, 0.4 * max(0.0, m.get("occ_face", 0) - 0.15))
    s *= 0.75 + 0.25 * (1 - min(1.0, 2.0 * max(0.0, m.get("occ_eyes_43", 0) - 0.1))) * m.get("in_43", 1.0)
    return round(max(0.0, s), 4)


def vlm_scores(cdir, ids):
    """Qwen 给 ids 这些成品封面打分 → ({id: 打分}, 模型自己的 Top3)。
    阿里云内容审核拦下某张图（DataInspectionFailed）时整批都会被拒：对半拆开再发，最后只有被拦的那张没有观感分。"""
    from llm import vision_json
    imgs = []
    for i, cid in enumerate(ids, 1):
        b = io.BytesIO()
        Image.open(cdir / f"{cid}.jpg").convert("RGB").resize(VLM_SIZE).save(b, "JPEG", quality=85)
        imgs.append((f"图{i}", b.getvalue()))
    try:
        res = vision_json(VLM_SYSTEM, VLM_PROMPT.format(n=len(ids)), imgs, label=f"封面打分 {cdir.parent.name}（{len(ids)} 张）")
    except Exception as e:  # noqa: BLE001
        if "DataInspectionFailed" not in str(e):
            raise
        if len(ids) == 1:
            print(f"  {ids[0]} 被内容审核拦下，这张只用技术分")
            return {}, []
        half = len(ids) // 2
        out = {}
        for part in (ids[:half], ids[half:]):
            out.update(vlm_scores(cdir, part)[0])
        return out, []
    num = lambda k: str(k).replace("图", "").strip()
    out = {}
    for x in res.get("items") or []:
        k = num(x.get("id", ""))
        if k.isdigit() and 1 <= int(k) <= len(ids):
            out[ids[int(k) - 1]] = x
    top = [ids[int(num(k)) - 1] for k in res.get("top3") or [] if num(k).isdigit() and 1 <= int(num(k)) <= len(ids)]
    return out, top


def _signature(cdir):
    return sorted([f.name, int(f.stat().st_mtime)] for f in cdir.iterdir()
                  if COVER_RE.match(f.name) or FRAME_RE.match(f.name))


def rank(d, force=False, use_vlm=True):
    """给 d/covers 排序，写 d/covers/rank.json；没变（候选和成品封面的修改时间都一样）就直接返回缓存。"""
    import cv2
    import make_cover
    cdir = d / "covers"
    out = cdir / "rank.json"
    sig = _signature(cdir) if cdir.exists() else []
    old = read_json(out, None)
    if old and not force and old.get("version") == VERSION and old.get("sig") == sig and (old.get("vlm") or not use_vlm):
        return old
    frames = {}
    for f in cdir.iterdir():
        m = FRAME_RE.match(f.name)
        if m:
            frames[f"{m[1] or 'cover'}_{m[2]}"] = (f.name, float(m[3]))
    ids = sorted(cid for cid in frames if (cdir / f"{cid}.jpg").exists())
    if not ids:
        return None
    det = cv2.FaceDetectorYN.create(str(make_cover.YUNET), "", (960, 540), 0.8, 0.3, 50)
    metrics = {cid: tech_metrics(cdir, cid, frames[cid][0], det) for cid in ids}
    sharps = sorted(m.get("sharp", 0) for m in metrics.values())
    pct = {cid: (np.searchsorted(sharps, m.get("sharp", 0), side="right") / len(sharps)) for cid, m in metrics.items()}
    tech = {cid: tech_score(metrics[cid], pct[cid]) for cid in ids}
    tmax = max(tech.values()) or 1.0
    vlm, vlm_top = ({}, [])
    if use_vlm:
        try:
            vlm, vlm_top = vlm_scores(cdir, ids)
        except Exception as e:  # noqa: BLE001 接口挂了就只用技术分
            print(f"  封面打分接口失败（{e}），只用技术分")
    items = []
    for cid in ids:
        v = vlm.get(cid) or {}
        t = tech[cid] / tmax
        if v:
            score = W_VLM * float(v.get("overall") or 0) / 10 + W_TECH * t
            if v.get("eyes") in ("closed", "half"):
                score *= 0.7 if v["eyes"] == "half" else 0.55
            if cid in vlm_top:
                score += 0.03 * (3 - vlm_top.index(cid))   # 模型自己的 Top3 小幅加分（打平时用）
        elif vlm:   # 别的图都有观感分、只有这张没有（被内容审核拦下）：观感按中间值 5 分算，免得只凭技术分排到前面
            score = W_VLM * 0.5 + W_TECH * t
        else:
            score = t
        mt = metrics[cid]   # 程序测的字挡眼睛（模型不判断这一项，见 VLM_PROMPT）
        score *= 1 - min(0.6, 2.0 * max(0.0, mt.get("occ_eyes", 0) - 0.1))
        items.append({"id": cid, "t": frames[cid][1], "score": round(score, 4), "tech": round(t, 3),
                      "vlm": v.get("overall"), "eyes": v.get("eyes"), "why": v.get("reason") or tech_reason(metrics[cid]),
                      "metrics": metrics[cid]})
    items.sort(key=lambda x: -x["score"])
    top = []
    for x in items:   # Top3 互相隔开 TOP_GAP 秒；凑不够再放开
        if len(top) < 3 and all(abs(x["t"] - y["t"]) >= TOP_GAP for y in top):
            top.append(x)
    for x in items:
        if len(top) < 3 and x not in top:
            top.append(x)
    order = top + [x for x in items if x not in top]
    for i, x in enumerate(order, 1):
        x["rank"] = i
    res = {"version": VERSION, "sig": sig, "vlm": bool(vlm), "created": time.strftime("%Y-%m-%d %H:%M"),
           "top3": [x["id"] for x in top], "vlm_top3": vlm_top, "items": order}
    write_json(out, res)
    return res


def tech_reason(m):
    """没有观感分时的一句话理由。"""
    if not m.get("faces"):
        return "没检测到正脸"
    bad = []
    if m.get("occ_eyes", 0) > 0.25:
        bad.append("字挡眼睛")
    if m["frontal"] < 2:
        bad.append("侧脸")
    if m["bright"] < 60:
        bad.append("脸偏暗")
    if m["edge"] and m["face_h"] < 0.5:
        bad.append("脸贴边")
    return "、".join(bad) or ("大正脸" if m["face_h"] >= 0.2 else "正脸清楚")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug")
    p.add_argument("songs", nargs="*", help="歌名（目录名），不写就是整场每首")
    p.add_argument("--force", action="store_true", help="忽略缓存重新打分")
    p.add_argument("--no-vlm", action="store_true", help="只用本地技术分，不调 Qwen")
    a = p.parse_args()
    c = Concert(a.slug)
    items = [it for it in c.song_items() if not a.songs or it["name"] in a.songs]
    if not items and (c.songs.exists()):   # singles 没有 setlist 里的 kind，按目录名
        items = [{"name": x.name} for x in sorted(c.songs.iterdir()) if not a.songs or x.name in a.songs]
    for it in items:
        r = rank(c.song_dir(it).resolve(), force=a.force, use_vlm=not a.no_vlm)
        if not r:
            print(f"{it['name']}: 没有候选封面")
            continue
        print(f"{it['name']}: Top3 " + "  ".join(
            f"#{x['rank']} {x['id']}（{x['score']:.2f}，{x['why']}）" for x in r["items"][:3]))
        for x in r["items"][3:]:
            print(f"    #{x['rank']} {x['id']} {x['score']:.2f} {x['why']}")


if __name__ == "__main__":
    main()
