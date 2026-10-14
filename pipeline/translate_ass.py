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

from llm import chat_json

PLAY_W, PLAY_H = 1920, 1080
LATIN_FONT = "Arial Rounded MT Bold"
CJK_FONT = "Hiragino Sans GB"      # 中文译文（\b1 加粗）
JA_FONT = "Hiragino Sans W6"       # 日文/含汉字的原文，Arial 没有这些字形，fallback 字体太细
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")

SYSTEM_PROMPT = """你是专业的歌词译者。用户给出一首歌按时间轴切分的歌词行（JSON 数组），
请逐行翻译成简体中文，要求：
- 输出 JSON: {"zh": [...]}，长度与输入完全一致，一一对应，不合并不拆分
- 结合整首歌上下文，译文自然、有歌词感，不要逐字硬译
- 纯语气词/拟声词（如 Oh, Uh-uh, Na-na, Yeah）或已经是中文的行，对应位置输出空字符串
- 片假名可能是外来语或日式英语，按读音还原成原词再翻译；任何一行都不要输出“意义不明”之类的说明，实在无法理解就输出空字符串
- 不要添加任何解释"""


def translate_api(lines, context):
    user = (f"歌曲: {context}\n" if context else "") + json.dumps(lines, ensure_ascii=False)
    for attempt in range(3):
        zh = chat_json(SYSTEM_PROMPT, user, label="翻译", effort=os.environ.get("TRANSLATE_EFFORT", "high")).get("zh", [])
        if len(zh) == len(lines):
            return [z.strip() for z in zh]
        print(f"返回行数 {len(zh)} != {len(lines)}，重试 {attempt + 1}/3")
    raise SystemExit("翻译行数始终对不上，请改用 --zh-file")


def build_ass(subs, zh, title, title_duration, style="bzrp"):
    return (build_ass_bzrp if style == "bzrp" else build_ass_modern)(subs, zh, title, title_duration)


def build_ass_bzrp(subs, zh, title, title_duration):
    """默认样式，与 lyrics/bzrp_v2.ass 完全一致：384x288 画布、Arial Rounded 23、描边 1、无阴影、底边距 50；
    标题也作为普通一行放在底部；格式 “原文 \\N♪ 中文 ♪”，不加任何行内标签。"""
    out = pysubs2.SSAFile()
    out.info.update({"PlayResX": "384", "PlayResY": "288", "ScaledBorderAndShadow": "yes"})
    out.styles["Default"] = pysubs2.SSAStyle(
        fontname=LATIN_FONT, fontsize=23,
        primarycolor=pysubs2.Color(255, 255, 255), secondarycolor=pysubs2.Color(255, 255, 255),
        outlinecolor=pysubs2.Color(0, 0, 0), backcolor=pysubs2.Color(0, 0, 0),
        outline=1, shadow=0, alignment=pysubs2.Alignment.BOTTOM_CENTER,
        marginl=10, marginr=10, marginv=50)
    if title:
        first = subs.events[0].start if subs.events else title_duration
        out.events.append(pysubs2.SSAEvent(start=0, end=min(title_duration, first), text=title))
    for e, z in zip(subs.events, zh):
        text = e.plaintext.replace("\n", " ").strip()
        if z and z != text:
            text += r" \N♪ " + z + " ♪"
        out.events.append(pysubs2.SSAEvent(start=e.start, end=e.end, text=text))
    return out


def build_ass_modern(subs, zh, title, title_duration):
    """1920x1080 画布、日文 Hiragino Sans W6、中文加粗、标题在顶部。"""
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
        t = (r"{\fn" + JA_FONT + "}" + title) if CJK_RE.search(title) else title
        out.events.append(pysubs2.SSAEvent(start=0, end=title_duration, text=t, style="Title"))
    for e, z in zip(subs.events, zh):
        text = e.plaintext.replace("\n", " ").strip()
        orig = text
        if CJK_RE.search(text):
            text = r"{\fn" + JA_FONT + "}" + text
        if z and z != orig:
            text += r"\N{\fn" + CJK_FONT + r"\b1\fs56}♪ " + z + " ♪"
        out.events.append(pysubs2.SSAEvent(start=e.start, end=e.end, text=text))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("srt")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--title", help="首行标题，如 '《Song》 Artist'")
    p.add_argument("--title-duration", type=int, default=4000, help="标题最长显示毫秒")
    p.add_argument("--zh-file")
    p.add_argument("--cache", help="按句缓存的译文 json（原文 -> 中文）；只翻缓存里没有的句子，翻完写回")
    p.add_argument("--style", choices=["bzrp", "modern"], default="bzrp",
                   help="bzrp=与 bzrp_v2.ass 相同（默认）；modern=1080p 画布、日文粗体、标题在顶部")
    a = p.parse_args()

    subs = pysubs2.load(a.srt)
    lines = [re.sub(r"\s+", " ", e.plaintext).strip() for e in subs.events]

    if a.zh_file:
        with open(a.zh_file, encoding="utf-8") as f:
            zh = [l.strip() for l in f.read().split("\n")]
        zh = (zh + [""] * len(lines))[:len(lines)]
    else:
        cache = {}
        if a.cache and os.path.exists(a.cache):
            cache = json.load(open(a.cache, encoding="utf-8"))
        todo = sorted({l for l in lines if l and l not in cache}, key=lines.index)
        if todo:
            # 只翻新句子，但把整首歌词（去重）作为上下文给模型，保证语气和已有译文一致
            uniq = sorted({l for l in lines if l}, key=lines.index)
            ctx = (a.title or "") + "\n整首歌词（仅作上下文，只需翻译下面 JSON 里的行）：\n" + "\n".join(uniq)
            for k, v in zip(todo, translate_api(todo, ctx)):
                cache[k] = v
        print(f"译文缓存: 复用 {len(set(lines)) - len(todo)} 句，新翻 {len(todo)} 句")
        zh = [cache.get(l, "") for l in lines]
        if a.cache:
            with open(a.cache, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1)

    build_ass(subs, zh, a.title, a.title_duration, a.style).save(a.output)
    print(f"写入 {a.output}（{len(lines)} 句，{sum(1 for z in zh if z)} 句含中文）")


if __name__ == "__main__":
    main()
