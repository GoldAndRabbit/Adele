#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-ASR-Flash 识别（阿里云百炼，支持歌唱识别、抗背景音乐），供 qwen_sequence / verify_qwen 调用。
接口与 Takit workers/src/tools/asr.ts 相同（OpenAI 兼容 chat/completions + input_audio），密钥 ALIYUN_BAILIAN_API_KEY。
注意：不要把歌词作为上下文传进去，模型会原样照抄上下文。
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
    import time
    for attempt in range(8):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + b64}}]}],
                extra_body={"asr_options": opts}, timeout=60)
            return r.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            # 429 限流：指数退避重试；其他错误重试 3 次
            limited = "429" in str(e) or "limit" in str(e).lower()
            if attempt == 7 or (not limited and attempt >= 2):
                print(f"  识别失败: {str(e)[:80]}")
                return None
            time.sleep(min(30, 2 ** attempt) if limited else 1)
