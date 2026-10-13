#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补 whisper 漏识别的段落：人声明显很响、但 whisper 超过 N 秒没有任何词的区间，单独重新识别后合并回去。

现场录音里 whisper 常把开头一整段（观众声、前奏和演唱混在一起）当成“没有语音”直接跳过，
单独截出那一段、让窗口从演唱处开始，通常就能识别出来。

python pipeline/fill_whisper_gaps.py --vocals separated/htdemucs/X/vocals.wav --json work/X/whisper/vocals.json --lang Japanese
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

HOP = 0.1          # 能量曲线 0.1s 一点
LOUD_DB = 20       # 比整首最响处（95 分位）低不超过 20dB 算“在唱”
MIN_GAP = 5.0      # 至少这么长的空白才补
MIN_VOICED = 0.5   # 空白里至少一半时间在唱


def vocal_db(path):
    """人声能量曲线（dB，相对整首 95 分位）。"""
    import librosa

    y, sr = librosa.load(path, sr=16000, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=int(sr * HOP), hop_length=int(sr * HOP))[0]
    db = 20 * np.log10(rms + 1e-9)
    return db - np.percentile(db, 95)


def clip_starts(db, s, e):
    """候选起点：空白起点、人声持续 1s 以上很响（-10dB）的位置，以及之后每隔 3s。"""
    starts = [s]
    loud = db[int(s / HOP):int(e / HOP)] > -10
    run_len = int(1 / HOP)
    for i in range(len(loud) - run_len):
        if loud[i:i + run_len].all():
            starts.append(s + i * HOP)
            break
    t = starts[-1] + 3
    while t < e - MIN_GAP / 2 and len(starts) < 4:
        starts.append(t)
        t += 3
    return sorted(set(round(x, 1) for x in starts))


def find_gaps(words, voiced, duration):
    """返回 [(开始秒, 结束秒)]：没有识别词、但大部分时间在唱的区间。"""
    edges = [0.0] + [t for w in words for t in (w["start"], w["end"])] + [duration]
    gaps = []
    for i in range(0, len(edges) - 1, 2):
        s, e = edges[i], edges[i + 1]
        if e - s < MIN_GAP:
            continue
        seg = voiced[int(s / HOP):int(e / HOP)]
        if len(seg) and seg.mean() >= MIN_VOICED:
            # 收紧到真正开始/结束唱的位置
            idx = np.where(seg)[0]
            gaps.append((s + idx[0] * HOP, s + (idx[-1] + 1) * HOP))
    return gaps


def transcribe_clip(whisper, vocals, start, end, model, lang):
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [whisper, str(vocals), "--model", model, "--temperature", "0.0", "--best_of", "5",
               "--beam_size", "5", "--condition_on_previous_text", "False", "--word_timestamps", "True",
               "--output_format", "json", "--output_dir", tmp,
               "--clip_timestamps", f"{max(0, start - 0.5):.2f},{end + 0.5:.2f}",
               "--no_speech_threshold", "0.95", "--logprob_threshold", "-2.0"]
        if lang:
            cmd += ["--language", lang]
        subprocess.run(cmd, check=True, capture_output=True)
        return json.loads((Path(tmp) / f"{Path(vocals).stem}.json").read_text())["segments"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vocals", required=True)
    p.add_argument("--json", required=True, help="whisper 主识别结果（会原地补充，原文件备份为 .orig.json）")
    p.add_argument("--whisper", default="whisper", help="whisper 命令路径")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--lang")
    a = p.parse_args()

    path = Path(a.json)
    data = json.loads(path.read_text())
    words = [w for s in data["segments"] for w in s.get("words", [])]
    db = vocal_db(a.vocals)
    voiced = db > -LOUD_DB
    gaps = find_gaps(words, voiced, len(voiced) * HOP)
    if not gaps:
        print("没有漏识别的段落")
        return

    backup = path.with_suffix(".orig.json")
    if not backup.exists():
        backup.write_text(path.read_text())
    added = 0
    for s, e in gaps:
        # whisper 对窗口起点很敏感：起点混着前奏/观众声时又会整段跳过，所以试几个起点取识别词最多的
        best, best_n = [], -1
        for st in clip_starts(db, s, e):
            segs = transcribe_clip(a.whisper, a.vocals, st, e, a.model, a.lang)
            n = sum(1 for sg in segs for w in sg.get("words", []) if s - 0.5 <= w["start"] < e + 0.2)
            print(f"  起点 {st:.1f}s -> {n} 个词")
            if n > best_n:
                best, best_n = segs, n
        new = best
        for seg in new:
            seg["words"] = [w for w in seg.get("words", []) if s - 0.5 <= w["start"] < e + 0.2]
            if seg["words"]:
                seg["start"], seg["end"] = seg["words"][0]["start"], seg["words"][-1]["end"]
                seg["text"] = "".join(w["word"] for w in seg["words"])
                data["segments"].append(seg)
                added += len(seg["words"])
        print(f"补识别 {int(s // 60)}:{s % 60:04.1f} - {int(e // 60)}:{e % 60:04.1f}")
    data["segments"].sort(key=lambda x: x["start"])
    path.write_text(json.dumps(data, ensure_ascii=False))
    print(f"共补 {len(gaps)} 段，{added} 个词；原结果备份 {backup}")


if __name__ == "__main__":
    main()
