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


_CACHE, _CACHE_LOCK = {}, __import__("threading").Lock()


def _cache():
    """环境变量 QWEN_CACHE=<json 路径> 时启用识别缓存（v2 精校用）：同一段音频 + 同一语言只识别一次，
    重跑结果不再每次不一样。没设置时（v1 默认）照旧每次都调接口。"""
    path = os.environ.get("QWEN_CACHE")
    if not path:
        return None, None
    if path not in _CACHE:
        f = Path(path)
        _CACHE[path] = json.loads(f.read_text()) if f.exists() else {}
    return path, _CACHE[path]


def transcribe(client, y, lang):
    data = wav_bytes(y)
    path, cache = _cache()
    if cache is not None:
        import hashlib
        key = hashlib.sha1(data + (lang or "").encode()).hexdigest()
        if key in cache:
            return cache[key]
        text = _transcribe(client, data, lang)
        if text is not None:   # 失败不缓存
            with _CACHE_LOCK:
                cache[key] = text
                f = Path(path)
                if f.exists():   # 别的进程（v2 精校里的 verify 子进程）写进去的条目合并进来，不覆盖
                    for k, v in json.loads(f.read_text()).items():
                        cache.setdefault(k, v)
                tmp = f.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(cache, ensure_ascii=False))
                tmp.replace(path)
        return text
    return _transcribe(client, data, lang)


def _transcribe(client, data, lang):
    b64 = base64.b64encode(data).decode()
    opts = {"enable_itn": False}
    if lang and lang != "auto":  # auto = 不指定语言，让模型自己判断（中英 / 英西混唱的串烧）
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
