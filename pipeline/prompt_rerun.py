#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用歌词提示 whisper 重识别不可信段落：声学打分找出不可信的连续句子（>=2 句），
对每段挑声学上最像的几句参考歌词作 initial_prompt，单独重识别这段人声，把结果替换进 whisper json。
之后照常跑 align_lyrics（reference 模式）+ refine_timing。识别结果只用来定位，字幕文字仍只来自参考歌词。

python pipeline/prompt_rerun.py ori_lyrics/X.srt --ref ori_lyrics/X.txt --vocals .../vocals.wav \
    --json work/X/whisper/vocals.json --lang ja -o work/X/whisper/vocals.prompted.json
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402

WHISPER_LANG = {"ja": "Japanese", "en": "English", "es": "Spanish"}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--json", required=True, help="原 whisper json")
    p.add_argument("--lang", default="en")
    p.add_argument("--whisper", default=str(Path(__file__).resolve().parent.parent / "my_venv" / "bin" / "whisper"))
    p.add_argument("--top", type=int, default=6, help="每段提示用几句歌词")
    p.add_argument("-o", "--output", required=True)
    a = p.parse_args()

    import pysubs2
    sc = acoustic.Scorer(a.vocals, a.lang)
    ev = pysubs2.load(a.srt).events
    v = np.array([sc.evidence(e.plaintext, e.start / 1000, e.end / 1000) for e in ev])
    min_ev = float(np.percentile(v, 25) - 0.5 * v.std())
    low = v < min_ev

    stretches, i = [], 0
    while i < len(ev):
        if not low[i]:
            i += 1
            continue
        j = i
        while j < len(ev) and low[j]:
            j += 1
        if j - i >= 2:
            stretches.append((max(0.0, ev[i].start / 1000 - 1.0), ev[j - 1].end / 1000 + 1.0))
        i = j

    refs = []
    for text, _ in acoustic.section_lines(a.ref):
        if text not in refs:
            refs.append(text)

    data = json.loads(Path(a.json).read_text())
    for t0, t1 in stretches:
        # 每句参考歌词在这段里任意位置的最佳声学分，取前 top 句作提示
        scored = []
        for text in refs:
            n = acoustic.char_count(sc, text)
            dur = max(1.0, n * 0.12)
            best = max(sc.evidence(text, s, min(t1, s + dur)) for s in np.arange(t0, max(t0 + 0.01, t1 - dur), 0.5))
            scored.append((best, text))
        prompt = " ".join(t for _, t in sorted(scored, reverse=True)[: a.top])
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [a.whisper, a.vocals, "--model", "large-v3", "--temperature", "0.0", "--beam_size", "5",
                   "--best_of", "5", "--condition_on_previous_text", "False", "--word_timestamps", "True",
                   "--output_format", "json", "--output_dir", tmp, "--initial_prompt", prompt,
                   "--clip_timestamps", f"{t0:.2f},{t1:.2f}",
                   "--no_speech_threshold", "0.95", "--logprob_threshold", "-2.0"]
            if a.lang in WHISPER_LANG:
                cmd += ["--language", WHISPER_LANG[a.lang]]
            subprocess.run(cmd, check=True, capture_output=True)
            new = json.loads((Path(tmp) / f"{Path(a.vocals).stem}.json").read_text())["segments"]
        # 原结果里这段的词去掉，换成新识别的
        for seg in data["segments"]:
            seg["words"] = [w for w in seg.get("words", []) if not (t0 <= w["start"] < t1)]
        n_words = 0
        for seg in new:
            seg["words"] = [w for w in seg.get("words", []) if t0 <= w["start"] < t1]
            if seg["words"]:
                seg["start"], seg["end"] = seg["words"][0]["start"], seg["words"][-1]["end"]
                data["segments"].append(seg)
                n_words += len(seg["words"])
        print(f"  {t0:.1f}-{t1:.1f}s 用 {a.top} 句歌词提示重识别 -> {n_words} 个词")
    data["segments"] = sorted([s for s in data["segments"] if s.get("words")], key=lambda s: s["start"])
    Path(a.output).write_text(json.dumps(data, ensure_ascii=False))
    print(f"不可信段落 {len(stretches)} 段；写入 {a.output}")


if __name__ == "__main__":
    main()
