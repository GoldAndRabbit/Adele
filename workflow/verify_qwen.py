#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐句 Qwen 复核：把每句字幕对应的人声单独截出来（前后各放 0.3s）交给 qwen3-asr-flash 识别，
和这句字幕的读音比对：
  - 匹配（>= OK）          保留
  - 不匹配、但识别结果明显是参考里另一句（>= SWAP，且比当前句高出 15 以上） 换成那一句
  - 不匹配、也认不出是哪句 记为可疑（报告里列时间点；--hide-suspect 时隐藏）
识别文字只用来比对，字幕文字仍只来自参考歌词。

python workflow/verify_qwen.py in.srt --ref posts/X/lyrics.txt --vocals .../vocals.wav --lang ja -o out.srt --report r.json
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
from textnorm import reading  # noqa: E402
from infer_insert import is_filler  # noqa: E402
from qwen_asr import ENDPOINT, SR, transcribe  # noqa: E402

OK, SWAP, MARGIN = 65, 75, 15
REACH = 3  # 换句只在参考歌词里前后 3 句之内找


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("--ref", required=True)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default=None)
    p.add_argument("--hide-suspect", action="store_true", help="可疑句全部隐藏")
    p.add_argument("--no-swap", dest="swap", action="store_false",
                   help="只复核不换句（歌词主导模式用：结构以歌词为准，识别只用来隐藏明确不对的句子）")
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
    ordered = [t for t, _ in acoustic.section_lines(a.ref)]
    ref_r = {t: reading(t) for t in set(ordered)}

    def ref_pos(text, prev):
        """这句在参考歌词里的位置（多处出现时取离上一句位置最近的；拆过的半句按包含关系找）。"""
        hits = [i for i, l in enumerate(ordered) if l == text] or [i for i, l in enumerate(ordered) if text and text in l]
        if not hits:
            return None
        return min(hits, key=lambda i: abs(i - (prev + 1))) if prev is not None else hits[0]

    def job(e):
        if is_filler(e.plaintext) or e.end - e.start < 600:
            return None
        s0, s1 = max(0, e.start / 1000 - 0.3), min(len(y) / SR, e.end / 1000 + 0.3)
        return transcribe(client, y[int(s0 * SR):int(s1 * SR)], a.lang)

    with ThreadPoolExecutor(3) as ex:
        asr = list(ex.map(job, subs.events))

    kept, swapped, suspect, out = 0, [], [], []
    heard = [{"start": round(e.start / 1000, 2), "end": round(e.end / 1000, 2), "text": e.plaintext, "heard": t}
             for e, t in zip(subs.events, asr)]  # 每句截出来识别到的文字（审核页并列显示用）
    failed, prev = 0, None
    events = list(subs.events)
    for n, (e, text) in enumerate(zip(events, asr)):
        pos = ref_pos(e.plaintext, prev)
        if pos is not None:
            prev = pos
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
        # 只允许换成参考歌词里前后 REACH 句之内的句子，且不能和前后字幕重复：
        # 说唱等短片段识别不稳，全曲范围找“最像的句子”会把别处的句子换进来
        neigh = {o.plaintext for o in events[max(0, n - 1):n + 2] if o is not e}
        cands = set()
        if pos is not None:
            cands = {ordered[k] for k in range(max(0, pos - REACH), min(len(ordered), pos + REACH + 1))}
        cands = {t for t in cands if t != e.plaintext and t not in neigh and len(ref_r[t]) >= 4}
        best = max(((fuzz.partial_ratio(ref_r[t], r), t) for t in cands), default=(0, None))
        if a.swap and best[1] and best[0] >= SWAP and best[0] - cur >= MARGIN:
            swapped.append({"start": round(e.start / 1000, 1), "score_before": round(cur), "score_after": round(best[0])})
            e.text = best[1]
            out.append(e)
        else:
            suspect.append({"start": round(e.start / 1000, 1), "end": round(e.end / 1000, 1), "score": round(cur)})
            hide = a.hide_suspect or cur < a.hide_below
            suspect[-1]["hidden"] = hide
            if not hide:
                out.append(e)
    # 收尾：按时间排序，同句重叠的去掉，不同句重叠的截断前一句，过短的丢掉
    out.sort(key=lambda e: e.start)
    clean = []
    for e in out:
        if clean and e.start < clean[-1].end:
            if e.plaintext == clean[-1].plaintext:
                clean[-1].end = max(clean[-1].end, e.end)
                continue
            clean[-1].end = max(clean[-1].start + 200, e.start - 30)
        if e.end - e.start >= 200:
            clean.append(e)
    subs.events = clean
    subs.save(a.output)
    if a.report:
        Path(a.report).write_text(json.dumps({"kept": kept, "swapped": swapped, "suspect": suspect, "lines": heard},
                                             ensure_ascii=False, indent=1))
    print(f"逐句 Qwen 复核：通过 {kept} 句，换句 {len(swapped)} 处，可疑 {len(suspect)} 处，识别失败 {failed} 句")
    for x in swapped:
        print(f"  换句 @{x['start']}s（匹配 {x['score_before']} -> {x['score_after']}）")
    for x in suspect:
        print(f"  可疑 {x['start']}-{x['end']}s（匹配 {x['score']}）" + ("，已隐藏" if x.get("hidden") else "，保留"))


if __name__ == "__main__":
    main()
