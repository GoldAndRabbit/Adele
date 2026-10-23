# -*- coding: utf-8 -*-
"""OpenAI 兼容的大模型调用，供应商配置与 Takit 一致；密钥放仓库根目录 .env。"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 与 Takit workers/src/agent/model.ts 相同的供应商表：(base_url, 密钥变量, 默认模型)
PROVIDERS = {
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "deepseek-v4-pro"),
    "aliyun": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "ALIYUN_BAILIAN_API_KEY", "qwen-max"),
    "siliconflow": ("https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY", "deepseek-ai/DeepSeek-V3"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4.1"),
}


def load_env(path=os.path.join(ROOT, ".env")):
    """读取 .env（不覆盖已有环境变量），省得每次 export。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def chat_json(system, user, temperature=0.3, label="LLM", effort=None):
    """发一轮对话，要求模型返回 JSON 对象，返回解析后的 dict。"""
    from openai import OpenAI

    load_env()
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    base_url, key_var, default_model = PROVIDERS[provider]
    if not os.environ.get(key_var):
        raise SystemExit(f"缺少 {key_var}（放到 {ROOT}/.env 或 export）")
    client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL", base_url), api_key=os.environ[key_var])
    model = os.environ.get("TRANSLATE_MODEL", default_model)
    # DeepSeek 思考模式：effort=None 关闭；low/medium/high 开启（歌词翻译默认 high，见 translate_ass.py）
    effort = effort or os.environ.get("LLM_EFFORT") or None
    extra, kw = {}, {"temperature": temperature}
    if provider == "deepseek":
        if effort:
            extra = {"thinking": {"type": "enabled"}, "reasoning_effort": effort}
            kw = {"max_tokens": 32768}  # 思考内容也计入 max_tokens
        else:
            extra = {"thinking": {"type": "disabled"}}
    print(f"{label}: {provider} / {model}" + (f" / 思考 {effort}" if effort else ""))
    import time
    last = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                **kw,
                response_format={"type": "json_object"},
                extra_body=extra,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            # 偶发返回空 choices / 空内容（输出被截断、服务端异常），重试
            if resp.choices and resp.choices[0].message and resp.choices[0].message.content:
                return json.loads(resp.choices[0].message.content)
            last = f"空响应 finish_reason={resp.choices[0].finish_reason if resp.choices else None}"
        except (json.JSONDecodeError, Exception) as e:  # noqa: BLE001
            last = str(e)[:120]
        print(f"  {label} 第 {attempt + 1} 次失败（{last}），重试")
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{label} 连续失败: {last}")


def vision_json(system, text, images, label="看图", model=None):
    """看图（OpenAI 兼容接口，默认阿里百炼 Qwen，模型名 deepseek 开头走 DeepSeek）：images 是 JPEG bytes 列表，要求模型返回 JSON 对象。
    元素也可以是 (标签, bytes)：标签作为文字放在那张图前面（多图打分时让模型按编号对上）。"""
    import base64
    import time
    from openai import OpenAI

    load_env()
    model = model or os.environ.get("VISION_MODEL", "qwen3.8-max")
    provider = "deepseek" if model.startswith("deepseek") else "aliyun"   # deepseek-v4-flash-vision-exp 等走 DeepSeek
    base_url, key_var, _ = PROVIDERS[provider]
    if not os.environ.get(key_var):
        raise SystemExit(f"缺少 {key_var}（放到 {ROOT}/.env 或 export）")
    client = OpenAI(base_url=base_url, api_key=os.environ[key_var])
    extra = {"thinking": {"type": "disabled"}} if provider == "deepseek" else {"enable_thinking": os.environ.get("VISION_THINKING") == "1"}
    print(f"{label}: {provider} / {model}（{len(images)} 张图）")
    content = []
    for b in images:
        if isinstance(b, tuple):
            content.append({"type": "text", "text": b[0]})
            b = b[1]
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}})
    content.append({"type": "text", "text": text})
    last = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(model=model, response_format={"type": "json_object"}, extra_body=extra, messages=[
                {"role": "system", "content": system}, {"role": "user", "content": content}])
            if resp.choices and resp.choices[0].message and resp.choices[0].message.content:
                return json.loads(resp.choices[0].message.content)
            last = "空响应"
        except Exception as e:  # noqa: BLE001
            if "DataInspectionFailed" in str(e):   # 内容审核拦图：重发同样的图结果一样，直接交给调用方处理
                raise RuntimeError(f"{label}: DataInspectionFailed（内容审核拦下了图片）") from e
            last = str(e)[:120]
        print(f"  {label} 第 {attempt + 1} 次失败（{last}），重试")
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{label} 连续失败: {last}")

