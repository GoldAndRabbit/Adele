# -*- coding: utf-8 -*-
"""观众合唱检测流程（song_crowd_workflow）：在对齐之后、翻译之前跑。

    第 1 步 找候选段：两个可靠锚点之间，有人声、但识别很碎（没有锚点）的区间，而且按 Genius 顺序这里该唱 ≥ 1 句
    第 2 步 各项证据独立打分：
        a. 识别碎片：区间里识别到的东西和该唱的歌词读音像不像（不像 = 听不清）
        b. 立体声：人声左右声道相关性比本首低（观众声来自现场环境话筒）
        c. 主唱在不在唱：音高稳定度比本首歌手唱段低
        d. 画面：截 3 帧给看图模型（Qwen-VL）：话筒朝观众 / 镜头拍观众 / 歌手没在唱
        e. 提示语：前面 15 s 有没有叫观众唱的话（canten / sing / everybody / todos …）
        f. 歌词顺序：这里该唱几句
    第 3 步 综合判定：观众合唱 / 不是 / 不确定，带置信度和每项证据
    第 4 步 自检（唱不唱得下）：按录音室版的唱速，这段该唱的句子要唱多久，和这段实际多长比；
        超过 PACE_MAX 倍（按 1.5 倍速也唱不完）= 现场在这里跳过了歌词，不是观众按原词合唱，改判「不是」（这段保持 v3 原样）
    合唱段的处理（place_crowd）：区间里该唱的句子按 Genius 顺序排进去，时间按录音室版歌词时间轴（LRC，lrclib.net）
        的时长比例分；没有 LRC 就均分。识别碎片只用来确认这里有人在唱。
输出 exp_v4/crowd.json。
"""

import json
import re
import urllib.parse
import urllib.request

import numpy as np

PACE_MAX = 1.5   # 第 4 步：该唱的句子按录音室唱速要唱多久 / 这段实际多长，超过这个就不算观众合唱

CUE = re.compile(r"\b(canten|cántenla|cantad|cantemos|todos|todo el mundo|sing|everybody|let me hear|cantate|tutti|"
                 r"歌って|みんな)\b", re.I)

P_VISION = """你在看一场演唱会视频里连续截下的几帧画面。判断这一段是不是「观众合唱」：
- mic_to_crowd：歌手是不是把话筒朝向观众（伸向台下 / 举向观众）
- crowd_shot：镜头是不是主要在拍观众（观众在唱、举手机、挥手）
- singer_singing：歌手是不是正对着话筒在唱
每项给 true / false / null（看不出来），再用一句话描述你看到的。
输出 JSON：{"mic_to_crowd": ..., "crowd_shot": ..., "singer_singing": ..., "seen": "一句话"}"""


# ---------------------------------------------------------------- 录音室版歌词时间轴（LRC）

def fetch_lrc(title, artist, lines, cache):
    """lrclib.net 搜录音室版的逐句时间轴，挑和 Genius 歌词最像的一份；结果缓存。返回 [(秒, 歌词)] 或 []。"""
    if cache.exists():
        return [tuple(x) for x in json.loads(cache.read_text())]
    from rapidfuzz import fuzz
    url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"track_name": title, "artist_name": artist})
    try:
        res = json.loads(urllib.request.urlopen(url, timeout=20).read())
    except Exception:  # noqa: BLE001
        res = []
    best, best_sc = [], 0
    for r in res:
        if not r.get("syncedLyrics"):
            continue
        lrc = []
        for m in re.finditer(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", r["syncedLyrics"]):
            lrc.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
        sc = sum(max((fuzz.ratio(l.lower(), t.lower()) for _, t in lrc), default=0) >= 80 for l in lines[:40])
        if sc > best_sc:
            best, best_sc = lrc, sc
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(best, ensure_ascii=False))
    return best


def lrc_durations(lrc, texts):
    """每句歌词在录音室版里唱多久（这句的时间到下一句的时间）；找不到的给 None。"""
    from rapidfuzz import fuzz
    out = []
    for t in texts:
        best = max(range(len(lrc)), key=lambda i: fuzz.ratio(t.lower(), lrc[i][1].lower()), default=None)
        if best is None or fuzz.ratio(t.lower(), lrc[best][1].lower()) < 70 or best + 1 >= len(lrc):
            out.append(None)
        else:
            out.append(max(1.0, min(12.0, lrc[best + 1][0] - lrc[best][0])))
    return out


# ---------------------------------------------------------------- 画面

def frames(video, offset, a, b, n=3):
    import cv2
    cap = cv2.VideoCapture(str(video))
    out = []
    for k in range(n):
        t = a + (b - a) * (k + 1) / (n + 1)
        cap.set(cv2.CAP_PROP_POS_MSEC, (offset + t) * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        h, w = fr.shape[:2]
        fr = cv2.resize(fr, (768, int(h * 768 / w)))
        out.append(cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes())
    cap.release()
    return out


def vision(video, offset, a, b, cache, key):
    import sys
    from workflow_v2.paths import ROOT
    sys.path.insert(0, str(ROOT / "workflow"))
    import llm
    if key in cache:
        return cache[key]
    imgs = frames(video, offset, a, b)
    res = llm.vision_json(P_VISION, f"这一段在歌曲里的 {a:.0f}~{b:.0f} 秒，共 {len(imgs)} 帧，按时间顺序。", imgs, label="看画面") if imgs else {}
    cache[key] = res
    return res


# ---------------------------------------------------------------- 检测

def detect(d, out_dir, occ, ly, cells, reads, dur, y, sr, video, offset, pitch, stereo, title, artist):
    """返回 crowd 段 [{s, e, a_k, b_k, want, verdict, confidence, evidence}]。"""
    from rapidfuzz import fuzz
    from .run import key_of
    vcache_f = out_dir / "crowd_vision.json"
    vcache = json.loads(vcache_f.read_text()) if vcache_f.exists() else {}
    anchors = sorted([o for o in occ if o["anchor"]], key=lambda o: o["s"])
    st_med = float(np.nanmedian([pitch.ratio(o["s"], o["e"]) for o in anchors])) if anchors else 0.6
    lrc = fetch_lrc(title, artist, ly.lines, d / "reports" / "lrc.json")
    # 没有录音室时间轴的句子：按这首歌自己已经对上的句子，中位每句唱多久
    line_dur = float(np.median([o["e"] - o["s"] for o in anchors])) if anchors else 3.0
    segs = []
    for a, b in zip(anchors, anchors[1:]):
        t0, t1 = a["e"], b["s"]
        if t1 - t0 < 4.0 or b["k"] <= a["k"] + 1:
            continue
        want = [k for k in range(a["k"] + 1, b["k"]) if ly.key[k]]
        if not want:
            continue
        from workflow_v2.gap_fill import voiced_ratio
        vr = voiced_ratio(y, sr, t0, t1)
        if vr < 0.3:
            continue
        # a. 识别碎片：区间里听到的文字和该唱的歌词有多像
        heard = " ".join(w["w"] for ws in reads for w in ws if t0 <= w["s"] < t1)
        target = " ".join(ly.lines[k] for k in want)
        sim = fuzz.partial_ratio(key_of(heard), key_of(target)) if heard else 0.0
        frag = sim < 70
        # b. 立体声
        c, med = stereo.at(t0, t1), stereo.median()
        st_drop = bool(np.isfinite(c) and np.isfinite(med) and c <= med - 0.1)
        # c. 主唱在不在唱
        steady = pitch.ratio(t0, t1)
        lead_weak = steady < st_med - 0.1
        # d. 画面
        vis = vision(video, offset, t0, t1, vcache, f"{t0:.1f}-{t1:.1f}") if video and video.exists() else {}
        vis_crowd = bool(vis.get("mic_to_crowd") or (vis.get("crowd_shot") and vis.get("singer_singing") is False))
        # e. 提示语
        before = " ".join(w["w"] for w in reads[0] if t0 - 15 <= w["s"] < t0 + 2)
        cue = bool(CUE.search(before))
        ev = {"识别碎片": {"值": round(sim), "成立": frag, "说明": "区间里听到的和该唱的歌词读音相似度（< 70 = 听不清）"},
              "立体声": {"值": None if not np.isfinite(c) else round(c - med, 2), "成立": st_drop, "说明": "比本首中位低 ≥ 0.1"},
              "主唱": {"值": round(steady, 2), "成立": lead_weak, "说明": f"音高稳定度比本首歌手唱段（{st_med:.2f}）低 0.1 以上"},
              "画面": {"值": vis, "成立": vis_crowd, "说明": "话筒朝观众，或镜头拍观众且歌手没在唱"},
              "提示语": {"值": before[-60:], "成立": cue, "说明": "前面 15 s 有没有叫观众唱的话"},
              "歌词顺序": {"值": len(want), "成立": True, "说明": "按 Genius 顺序这里该唱几句"}}
        votes = sum(1 for k in ("识别碎片", "立体声", "主唱", "提示语") if ev[k]["成立"])
        if vis_crowd and frag:
            verdict, conf = "观众合唱", 0.9
        elif vis_crowd or (frag and votes >= 3):
            verdict, conf = "观众合唱", 0.7
        elif frag and votes >= 2:
            verdict, conf = "不确定", 0.5
        else:
            verdict, conf = "不是", 0.2
        # 第 4 步 自检：这段时间唱不唱得下这么多句
        durs = lrc_durations(lrc, [ly.lines[k] for k in want]) if lrc else [None] * len(want)
        need = sum(x or line_dur for x in durs)
        pace = need / (t1 - t0)
        ev["唱速"] = {"值": round(pace, 2), "成立": pace <= PACE_MAX,
                    "说明": f"该唱的 {len(want)} 句按录音室唱速要 {need:.0f}s，这段 {t1 - t0:.0f}s；超过 {PACE_MAX} 倍 = 唱不下，现场跳过了歌词"}
        if verdict == "观众合唱" and pace > PACE_MAX:
            verdict, conf = "不是", 0.2
        segs.append({"s": round(t0, 2), "e": round(t1, 2), "a_k": a["k"], "b_k": b["k"], "want": want,
                     "verdict": verdict, "confidence": conf, "evidence": ev, "heard": heard[:200]})
    vcache_f.write_text(json.dumps(vcache, ensure_ascii=False, indent=1))
    (out_dir / "crowd.json").write_text(json.dumps({"segments": segs, "lrc_lines": len(lrc)}, ensure_ascii=False, indent=1))
    return segs, lrc


def place_crowd(occ, segs, ly, lrc, cells):
    """判成观众合唱的段：把原来在这个区间里的非锚点行去掉，该唱的句子按 Genius 顺序排进去，
    时间按录音室版的时长比例分（找不到时长的按平均）。"""
    for sg in segs:
        if sg["verdict"] != "观众合唱":
            continue
        t0, t1 = sg["s"], sg["e"]
        occ[:] = [o for o in occ if o["anchor"] or not (t0 - 0.2 <= o["s"] < t1)]
        durs = lrc_durations(lrc, [ly.lines[k] for k in sg["want"]]) if lrc else [None] * len(sg["want"])
        known = [x for x in durs if x]
        avg = float(np.mean(known)) if known else 1.0
        durs = [x or avg for x in durs]
        # 只排在有人声的那部分：区间开头如果有很长的空白（间奏），从第一个识别到的碎片开始
        first = min([c["s"] for c in cells if t0 <= c["s"] < t1] or [t0])
        start = max(t0 + 0.1, first - 0.5)
        span = t1 - 0.1 - start
        scale = span / sum(durs)
        t = start
        for k, dd in zip(sg["want"], durs):
            occ.append({"k": k, "cells": [], "toks": [], "filled": True, "crowd": True, "coverage": 0.0, "sim": 0.0,
                        "support": 0.0, "cands": [], "s": t, "e": t + dd * scale - 0.05, "natural": True, "anchor": False,
                        "seq": True, "between": True, "conf": 0.0, "heard": "（观众合唱）"})
            t += dd * scale
    occ.sort(key=lambda o: o["s"])
    return occ
