#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-ASR-Flash（阿里云百炼，支持歌唱识别、抗背景音乐）滑窗识别人声，产出“这几秒唱了什么”的锚点。
接口与 Takit workers/src/tools/asr.ts 相同（OpenAI 兼容 chat/completions + input_audio），密钥 ALIYUN_BAILIAN_API_KEY。
qwen3-asr-flash 同步接口不给时间戳，所以用短窗口（默认 8s，步长 4s）换时间分辨率；精确时间仍交给 MMS 强制对齐。

python pipeline/qwen_asr.py --vocals separated/htdemucs/X/vocals.wav --lang ja -o work/X/qwen_windows.json
"""

import argparse
import base64
import io
import json
import os
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3-asr-flash"
SR = 16000


def wav_bytes(y):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def transcribe(client, y, lang):
    b64 = base64.b64encode(wav_bytes(y)).decode()
    opts = {"enable_itn": False}
    if lang:
        opts["language"] = lang
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + b64}}]}],
                extra_body={"asr_options": opts}, timeout=60)
            return r.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"  识别失败: {e}")
                return ""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lang", default=None, help="ja / en / zh ...，不填自动识别")
    p.add_argument("--win", type=float, default=8.0)
    p.add_argument("--hop", type=float, default=4.0)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("-o", "--output", required=True)
    a = p.parse_args()

    import librosa
    from openai import OpenAI

    llm.load_env()
    if not os.environ.get("ALIYUN_BAILIAN_API_KEY"):
        sys.exit("缺少 ALIYUN_BAILIAN_API_KEY（.env）")
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(a.vocals, sr=SR, mono=True)
    dur = len(y) / SR
    starts = list(np.arange(0, max(0.01, dur - a.win / 2), a.hop))
    rms = lambda s: float(np.sqrt(np.mean(y[int(s * SR):int((s + a.win) * SR)] ** 2) + 1e-12))
    loud = np.percentile([rms(s) for s in starts], 95)

    def job(s):
        if rms(s) < loud * 0.05:  # 基本没人声的窗口跳过
            return {"start": round(s, 2), "end": round(min(dur, s + a.win), 2), "text": ""}
        text = transcribe(client, y[int(s * SR):int((s + a.win) * SR)], a.lang)
        return {"start": round(s, 2), "end": round(min(dur, s + a.win), 2), "text": text}

    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(job, starts))
    Path(a.output).write_text(json.dumps({"model": MODEL, "win": a.win, "hop": a.hop, "windows": res},
                                         ensure_ascii=False, indent=1))
    print(f"Qwen3-ASR 滑窗识别 {len(res)} 个窗口（{a.win}s/{a.hop}s），非空 {sum(1 for r in res if r['text'])}；写入 {a.output}")


if __name__ == "__main__":
    main()
