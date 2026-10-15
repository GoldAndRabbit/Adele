#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐句 Qwen 复核：把每句字幕对应的人声单独截出来（前后各放 0.3s）交给 qwen3-asr-flash 识别，
和这句字幕的读音比对：
  - 匹配（>= OK）          保留
  - 不匹配、但识别结果明显是参考里另一句（>= SWAP，且比当前句高出 15 以上） 换成那一句
  - 不匹配、也认不出是哪句 记为可疑（报告里列时间点；--hide-suspect 时隐藏）
识别文字只用来比对，字幕文字仍只来自参考歌词。

python pipeline/verify_qwen.py in.srt --ref ori_lyrics/X.txt --vocals .../vocals.wav --lang ja -o out.srt --report r.json
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pysubs2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acoustic  # noqa: E402
import llm  # noqa: E402
from align_lyrics import reading  # noqa: E402
from infer_insert import is_filler  # noqa: E402
from qwen_asr import ENDPOINT, SR, transcribe  # noqa: E402

OK, SWAP, MARGIN = 65, 75, 15


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--hide-suspect", action="store_true", help="可疑句全部隐藏")
    p.add_argument("--hide-below", type=float, default=30,
                   help="可疑句里匹配分低于这个的隐藏（Qwen 明确认为不是这句）；其余可疑句保留并列出")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    a = p.parse_args()

    import librosa
    from openai import OpenAI
    from rapidfuzz import fuzz

    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    subs = pysubs2.load(a.srt)
    refs = sorted({t for t, _ in acoustic.section_lines(a.ref)}, key=lambda t: t)
    ref_r = {t: reading(t) for t in refs}

    def job(e):
        if is_filler(e.plaintext) or e.end - e.start < 600:
            return None
        s0, s1 = max(0, e.start / 1000 - 0.3), min(len(y) / SR, e.end / 1000 + 0.3)
        return transcribe(client, y[int(s0 * SR):int(s1 * SR)], a.lang)

    with ThreadPoolExecutor(3) as ex:
        asr = list(ex.map(job, subs.events))

    kept, swapped, suspect, out = 0, [], [], []
    failed = 0
    for e, text in zip(subs.events, asr):
        if text is None:
            if not is_filler(e.plaintext) and e.end - e.start >= 600:
                failed += 1  # 识别失败（限流等）不算通过
            out.append(e)
            continue
        r = reading(text)
        cur = fuzz.partial_ratio(reading(e.plaintext), r) if r else 0
        if cur >= OK or len(r) < 4:
            kept += 1
            out.append(e)
            continue
        best = max(((fuzz.partial_ratio(rr, r), t) for t, rr in ref_r.items() if len(rr) >= 4), default=(0, None))
        if best[1] and best[0] >= SWAP and best[0] - cur >= MARGIN:
            swapped.append({"start": round(e.start / 1000, 1), "score_before": round(cur), "score_after": round(best[0])})
            e.text = best[1]
            out.append(e)
        else:
            suspect.append({"start": round(e.start / 1000, 1), "end": round(e.end / 1000, 1), "score": round(cur)})
            hide = a.hide_suspect or cur < a.hide_below
            suspect[-1]["hidden"] = hide
            if not hide:
                out.append(e)
    subs.events = out
    subs.save(a.output)
    if a.report:
        Path(a.report).write_text(json.dumps({"kept": kept, "swapped": swapped, "suspect": suspect},
                                             ensure_ascii=False, indent=1))
    print(f"逐句 Qwen 复核：通过 {kept} 句，换句 {len(swapped)} 处，可疑 {len(suspect)} 处，识别失败 {failed} 句")
    for x in swapped:
        print(f"  换句 @{x['start']}s（匹配 {x['score_before']} -> {x['score_after']}）")
    for x in suspect:
        print(f"  可疑 {x['start']}-{x['end']}s（匹配 {x['score']}）" + ("，已隐藏" if x.get("hidden") else "，保留"))


if __name__ == "__main__":
    main()
