#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
srt 原文歌词 -> 双语 ass（原文 \\N ♪ 中文 ♪），时间轴严格不变。

中文来源二选一:
  1) 默认调用 OpenAI 兼容接口，供应商配置与 Takit 一致，密钥放在仓库根目录 .env
       LLM_PROVIDER     deepseek(默认) / aliyun / siliconflow / openai
       DEEPSEEK_API_KEY / ALIYUN_BAILIAN_API_KEY / SILICONFLOW_API_KEY / OPENAI_API_KEY
       TRANSLATE_MODEL  可选，默认按供应商取（deepseek-v4-pro / qwen-max / ...）
  2) --zh-file: 自己准备的中文，每行对应 srt 的一句，空行表示该句不翻译

python pipeline/translate_ass.py ori_lyrics/bzrp.srt -o lyrics/bzrp.ass --title "《Song》 Artist"
"""

import argparse
import json
import os
import re

import pysubs2

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

PLAY_W, PLAY_H = 1920, 1080
LATIN_FONT = "Arial Rounded MT Bold"
CJK_FONT = "Hiragino Sans GB"

SYSTEM_PROMPT = """你是专业的歌词译者。用户给出一首歌按时间轴切分的歌词行（JSON 数组），
请逐行翻译成简体中文，要求：
- 输出 JSON: {"zh": [...]}，长度与输入完全一致，一一对应，不合并不拆分
- 结合整首歌上下文，译文自然、有歌词感，不要逐字硬译
- 纯语气词/拟声词（如 Oh, Uh-uh, Na-na, Yeah）或已经是中文的行，对应位置输出空字符串
- 不要添加任何解释"""


def translate_api(lines, context):
    from openai import OpenAI

    load_env()
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    base_url, key_var, default_model = PROVIDERS[provider]
    if not os.environ.get(key_var):
        raise SystemExit(f"缺少 {key_var}（放到 {ROOT}/.env 或 export），或改用 --zh-file")
    client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL", base_url), api_key=os.environ[key_var])
    model = os.environ.get("TRANSLATE_MODEL", default_model)
    # DeepSeek 默认关闭思考模式：翻译不需要长推理，也避免 JSON 被截断
    extra = {"thinking": {"type": "disabled"}} if provider == "deepseek" else {}
    print(f"翻译: {provider} / {model}")
    user = (f"歌曲: {context}\n" if context else "") + json.dumps(lines, ensure_ascii=False)
    for attempt in range(3):
        resp = client.chat.completions.create(
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            extra_body=extra,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}],
        )
        zh = json.loads(resp.choices[0].message.content).get("zh", [])
        if len(zh) == len(lines):
            return [z.strip() for z in zh]
        print(f"返回行数 {len(zh)} != {len(lines)}，重试 {attempt + 1}/3")
    raise SystemExit("翻译行数始终对不上，请改用 --zh-file")


def build_ass(subs, zh, title, title_duration):
    out = pysubs2.SSAFile()
    out.info.update({"PlayResX": str(PLAY_W), "PlayResY": str(PLAY_H),
                     "ScaledBorderAndShadow": "yes", "WrapStyle": "0"})
    out.styles["Default"] = pysubs2.SSAStyle(
        fontname=LATIN_FONT, fontsize=64,
        primarycolor=pysubs2.Color(255, 255, 255), outlinecolor=pysubs2.Color(0, 0, 0),
        backcolor=pysubs2.Color(0, 0, 0, 128),
        outline=2.5, shadow=1, alignment=pysubs2.Alignment.BOTTOM_CENTER,
        marginl=60, marginr=60, marginv=70)

    # 标题放在顶部单独一个样式，开头就有歌词时也不会和歌词叠在一起
    out.styles["Title"] = out.styles["Default"].copy()
    out.styles["Title"].alignment = pysubs2.Alignment.TOP_CENTER
    out.styles["Title"].marginv = 60
    if title:
        out.events.append(pysubs2.SSAEvent(start=0, end=title_duration, text=title, style="Title"))
    for e, z in zip(subs.events, zh):
        text = e.plaintext.replace("\n", " ").strip()
        if z and z != text:
            text += r"\N{\fn" + CJK_FONT + r"\fs56}♪ " + z + " ♪"
        out.events.append(pysubs2.SSAEvent(start=e.start, end=e.end, text=text))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--title", help="首行标题，如 '《Song》 Artist'")
    p.add_argument("--title-duration", type=int, default=4000, help="标题最长显示毫秒")
    p.add_argument("--zh-file")
    a = p.parse_args()

    subs = pysubs2.load(a.srt)
    lines = [re.sub(r"\s+", " ", e.plaintext).strip() for e in subs.events]

    if a.zh_file:
        with open(a.zh_file, encoding="utf-8") as f:
            zh = [l.strip() for l in f.read().split("\n")]
        zh = (zh + [""] * len(lines))[:len(lines)]
    else:
        zh = translate_api(lines, a.title)

    build_ass(subs, zh, a.title, a.title_duration).save(a.output)
    print(f"写入 {a.output}（{len(lines)} 句，{sum(1 for z in zh if z)} 句含中文）")


if __name__ == "__main__":
    main()
