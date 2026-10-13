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


def chat_json(system, user, temperature=0.3, label="LLM"):
    """发一轮对话，要求模型返回 JSON 对象，返回解析后的 dict。"""
    from openai import OpenAI

    load_env()
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    base_url, key_var, default_model = PROVIDERS[provider]
    if not os.environ.get(key_var):
        raise SystemExit(f"缺少 {key_var}（放到 {ROOT}/.env 或 export）")
    client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL", base_url), api_key=os.environ[key_var])
    model = os.environ.get("TRANSLATE_MODEL", default_model)
    # DeepSeek 默认关闭思考模式：这些任务不需要长推理，也避免 JSON 被截断
    extra = {"thinking": {"type": "disabled"}} if provider == "deepseek" else {}
    print(f"{label}: {provider} / {model}")
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        extra_body=extra,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content)
