# -*- coding: utf-8 -*-
"""歌曲中间随机出现的半透明 logo 水印：先只出「计划」（什么时候、在哪），审核页预览；人工确认后成品渲染时才加进视频。

每首 2 次（歌曲 40%~60%、75%~90% 处各随机一次），每次 3 s（淡入淡出各 0.5 s），透明度 60%、带一圈淡的深色阴影，宽度约画面 8%；
时间避开结尾 10 s 和讲话段；位置在几个候选区域里随机，避开底部字幕区、左上角固定 logo 和人脸。
随机种子按歌名固定，同一首每次结果一样。结果写到歌曲目录的 watermark.json（时间是歌曲内时间）。

    .venv/bin/python -m workflow_v4.watermark song shakira_madrid_2026 37_bzrp_music_sessions_53
    .venv/bin/python -m workflow_v4.watermark post lose_yourself_2009
"""

import hashlib
import json
import random

LOGO_AR = 3936 / 1256        # assets/adele-logo.png 的宽高比
WIDTH = 0.08                 # 水印宽度 / 画面宽度
OPACITY = 0.6                # 白色 logo 在亮的舞台上 30% 几乎看不见（实测），加深色阴影 + 60%
DUR, FADE = 3.0, 0.5
EDGE = 10.0                  # 结尾这么多秒内不出现
WINDOWS = [(0.40, 0.60), (0.75, 0.90)]   # 每首两次：歌曲 40%~60%、75%~90% 处各随机一次（开头字幕还没出来，不放）
# 候选区域（左上角 x、y 的范围，占画面的比例）：右上、右中、左中、上中；底部字幕区（y > 0.68）和左上角固定 logo 不用
ZONES = [((0.84, 0.90), (0.05, 0.14)), ((0.84, 0.90), (0.36, 0.50)), ((0.02, 0.08), (0.36, 0.50)), ((0.40, 0.52), (0.04, 0.10))]


def faces_at(video, t, offset, yunet):
    """视频里 [t, t+DUR] 采三帧，返回人脸框（占画面比例的 x0, y0, x1, y1）。"""
    import cv2
    cap = cv2.VideoCapture(str(video))
    out = []
    for dt in (0.2, DUR / 2, DUR - 0.2):
        cap.set(cv2.CAP_PROP_POS_MSEC, (offset + t + dt) * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        scale = 640 / w
        small = cv2.resize(frame, (640, int(h * scale)))
        yunet.setInputSize((small.shape[1], small.shape[0]))
        _, det = yunet.detect(small)
        for d in (det if det is not None else []):
            x, y, fw, fh = d[:4] / scale
            # 人脸框往外扩一圈（头发、手、麦克风）
            out.append(((x - fw * 0.5) / w, (y - fh * 0.6) / h, (x + fw * 1.5) / w, (y + fh * 1.8) / h))
    cap.release()
    return out


def plan(name, dur, video, offset, avoid):
    """avoid：不出现的时间段 [(起, 止)]（讲话）。"""
    import cv2
    from workflow_v2.paths import ROOT
    rnd = random.Random(int(hashlib.sha1(name.encode()).hexdigest()[:8], 16))
    yunet = cv2.FaceDetectorYN.create(str(ROOT / "models" / "yunet" / "face_detection_yunet_2023mar.onnx"), "", (640, 360))
    items = []
    for fa, fb in WINDOWS:
        a, b = dur * fa, min(dur * fb, dur - EDGE) - DUR
        for _ in range(20):   # 时间：这个区间里随机，避开讲话
            t = round(rnd.uniform(a, max(a, b)), 2)
            if not any(s - 1 < t + DUR and t < e + 1 for s, e in avoid):
                break
        faces = faces_at(video, t, offset, yunet) if video and video.exists() else []
        h = WIDTH * 16 / 9 / LOGO_AR   # 水印高度 / 画面高度（按 16:9）
        pick = None
        for _ in range(40):           # 位置：候选区域里随机，不压人脸
            (x0, x1), (y0, y1) = rnd.choice(ZONES)
            x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
            box = (x, y, x + WIDTH, y + h)
            if not any(box[0] < f[2] and f[0] < box[2] and box[1] < f[3] and f[1] < box[3] for f in faces):
                pick = (x, y)
                break
        if pick is None:
            continue   # 每个候选位置都会压到人脸：这一次不出
        items.append({"t": t, "dur": DUR, "fade": FADE, "x": round(pick[0], 4), "y": round(pick[1], 4), "faces": len(faces)})
    return {"logo": "assets/adele-logo.png", "opacity": OPACITY, "width": WIDTH, "items": items}


def speech_spans(d):
    f = d / "exp_v4" / "lines.json"
    if not f.exists():
        return []
    return [(r["start_ms"] / 1000, r["end_ms"] / 1000) for r in json.loads(f.read_text()) if r.get("speech")]


def run_song(slug, name):
    from workflow_v2.paths import Concert, read_json
    c = Concert(slug)
    d = c.song_dir(c.item(name))
    info = read_json(d / "song.json", {})
    sl, pv = info.get("slice") or [0, 0], info.get("preview") or [0, 0]
    out = plan(name, sl[1] - sl[0], d / "preview.mp4", sl[0] - pv[0], speech_spans(d))
    (d / "watermark.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(name, [(x["t"], x["x"], x["y"]) for x in out["items"]])


def run_post(name):
    import subprocess
    from workflow_v2.paths import ROOT
    d = ROOT / "posts" / name
    video = d / "source.mp4"
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True).stdout.strip())
    out = plan(name, dur, video, 0.0, speech_spans(d))
    (d / "watermark.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(name, [(x["t"], x["x"], x["y"]) for x in out["items"]])


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "post":
        run_post(sys.argv[2])
    else:
        run_song(sys.argv[2], sys.argv[3])
