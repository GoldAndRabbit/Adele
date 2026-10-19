# -*- coding: utf-8 -*-
"""二次翻译（中文 v2）：精校、v1 翻译都完成以后，把整首字幕（原文 + v1 中文，按时间顺序）一次交给模型，
重写一版更有画面感、表现力的中文。v1 翻译不动；v2 写到 exp_v3/zh2.json 和 exp_v3/lyrics_zh2.ass。

    .venv/bin/python -m workflow_v3.retranslate song shakira_madrid_2026 37_bzrp_music_sessions_53
    .venv/bin/python -m workflow_v3.retranslate post lose_yourself_2009
"""

import hashlib
import json
import os
import re

MODEL = "deepseek-flash"   # DeepSeek v4.1 flash
EFFORT = "high"

PROMPT = """你是顶尖的中文歌词译者和作词人。用户给出一首歌按时间轴排好的全部字幕（JSON 数组），每一项有：
- orig：原文（一行字幕）
- v1：已有的中文初译（逐行翻的，意思基本对，但常常平淡、直译、前后不连贯）
- type：「歌词」或「讲话」（歌手在台上对观众说的话）

请通读整首歌（结合「歌曲解读」），重写一版中文 v2，要求：
- 输出 JSON：{"notes": [...], "zh": [...]}
  - notes：先写难点注释——这首歌里的俚语、黑话、双关、比喻、典故，每条一句：原文片段 = 在这首歌里指什么 → 打算怎么译
  - zh：长度和输入完全一致，一项对应一项
- **更有画面感和表现力**：用具体的意象、动作、色彩、情绪代替抽象的字面直译，读起来像一首好的中文歌词；
  可以用对仗、押韵、节奏感，但不要堆砌辞藻
- **忠实原意**：不加原文没有的情节和意思；俚语、双关、说唱黑话译出它在这首歌里的真实含义
- **俚语、比喻里用动物、物品指人的，译出所指，不留字面意象**：先弄清在这首歌里指的是谁 / 什么。
  例：BZRP「Sorry, baby, hace rato / Que yo debí botar ese gato」的 gato 是拉美俚语，指那个不值得的男人（前任），
  译「抱歉宝贝，我早就该 / 把那个渣男扫地出门」，不是「把那只猫扔出门外」
- 一句话被切成几行时，先连起来理解，再按行切回去；相邻行之间可以调整语序，但每一行的中文要对应这一行唱的时候
- **核心句要有高度**：先找出这首歌的核心句（歌名所在的句子、副歌的主旨句、表达态度 / 宣言的金句），
  把它背后的态度和主张译出来，读起来像一句能被记住、被转发的金句，可以用感叹号；不要停在字面。
  例：「Las mujeres ya no lloran, las mujeres facturan」不是「女人不再哭泣，女人要赚钱」，
  而是「女人不再流泪，女人要为自己买单！」——讲的是女性独立、自己掌控人生
- 「已定译法」里的句子照抄已定的中文（用户亲自改过的），其它句子的语气和它保持一致
- 同一句歌词（副歌）反复出现时，译法保持一致
- 每行简短，适合做字幕：一般不超过 18 个汉字
- 专有名词用中国观众熟悉的通行译名，中文里不夹外文（Ferrari→法拉利，Twingo→雷诺，Shakira→夏奇拉）；
  称呼女性不用「妞」；结巴式重复的名字按中文译名的第一个字重复（Sha-Sha-Shakira→夏-夏-夏奇拉）
- type 是「讲话」的：用自然的口语，不要写成歌词腔
- 纯语气词 / 拟声词的行（Oh、Uh-uh、Yeah）输出空字符串；句中的语气词不要译成「哦 / 耶 / 啊」
- 不要加 ♪，不要任何解释"""


FIXED_FILE = __import__("pathlib").Path(__file__).with_name("zh_fixed.json")
FIXED = json.loads(FIXED_FILE.read_text()) if FIXED_FILE.exists() else {}   # 用户定稿的译法：{原文: 中文}


def _n(t):
    """比较原文用：小写、去标点和多余空格。"""
    return re.sub(r"[^\w]+", " ", t.lower()).strip()


def ass_events(path):
    import pysubs2
    subs = pysubs2.load(str(path))
    out = []
    for i, e in enumerate(subs.events):
        parts = [x.strip() for x in e.text.replace("\\n", "\\N").split("\\N")]
        clean = [pysubs2.SSAEvent(text=x).plaintext.strip() for x in parts]
        orig = clean[0] if clean else ""
        zh = clean[1] if len(clean) > 1 else ""
        out.append({"i": i, "start_ms": e.start, "style": e.style, "orig": orig,
                    "zh1": re.sub(r"^♪\s*|\s*♪$", "", zh).strip(), "title": orig.startswith("《")})
    return subs, out


def retranslate(d, out_dir):
    import sys
    from workflow_v2.paths import ROOT
    sys.path.insert(0, str(ROOT / "workflow"))
    import llm

    subs, evs = ass_events(out_dir / "lyrics.ass")
    items = [e for e in evs if not e["title"] and e["orig"]]
    if not items:
        return []
    cache = json.loads((d / "zh_cache.json").read_text()) if (d / "zh_cache.json").exists() else {}
    brief = cache.get("__brief__", "")
    payload = [{"orig": e["orig"], "v1": e["zh1"], "type": "讲话" if e["style"] == "Speech" else "歌词"} for e in items]
    key = hashlib.sha1((MODEL + PROMPT + json.dumps(payload, ensure_ascii=False) +
                        json.dumps(FIXED, ensure_ascii=False)).encode()).hexdigest()
    f = out_dir / "zh2.json"
    old = json.loads(f.read_text()) if f.exists() else {}
    if old.get("key") == key:
        zh2 = old["zh2"]
    else:
        os.environ["TRANSLATE_MODEL"] = MODEL
        fixed_here = {k: v for k, v in FIXED.items() if any(_n(e["orig"]) == _n(k) for e in items)}
        user = ("歌曲解读：\n" + brief + "\n\n" if brief else "") + \
            ("已定译法：\n" + json.dumps(fixed_here, ensure_ascii=False) + "\n\n" if fixed_here else "") + \
            json.dumps(payload, ensure_ascii=False)
        zh2, notes = None, []
        for _ in range(3):
            res = llm.chat_json(PROMPT, user, label="二次翻译", effort=EFFORT)
            got = res.get("zh", [])
            if len(got) == len(items):
                zh2 = [str(z).strip() for z in got]
                notes = [str(x) for x in res.get("notes", [])]
                break
            print(f"  返回 {len(got)} 行，应为 {len(items)} 行，重试")
        if zh2 is None:
            raise RuntimeError("二次翻译行数始终对不上")
    # 用户定稿的译法强制替换（模型偶尔没照抄）
    zh2 = [next((v for k, v in FIXED.items() if _n(k) == _n(e["orig"])), z) for e, z in zip(items, zh2)]
    if old.get("key") == key:
        notes = old.get("notes", [])
    f.write_text(json.dumps({"key": key, "model": MODEL, "effort": EFFORT, "zh2": zh2, "notes": notes,
                             "items": [{"start_ms": e["start_ms"], "orig": e["orig"], "zh1": e["zh1"], "zh2": z}
                                       for e, z in zip(items, zh2)]}, ensure_ascii=False, indent=1))
    # 中文 v2 版字幕文件（预览用）：只换中文那一行，样式、♪ 规则和 v1 一样（讲话不加 ♪）
    by_i = {e["i"]: z for e, z in zip(items, zh2)}
    for i, ev in enumerate(subs.events):
        if i not in by_i:
            continue
        parts = ev.text.replace("\\n", "\\N").split("\\N")
        z = re.sub(r"[。.]$", "", by_i[i])
        if not z:
            ev.text = parts[0].rstrip()
            continue
        line = z if ev.style == "Speech" else f"♪ {z} ♪"
        ev.text = parts[0].rstrip() + r" \N" + line
    subs.save(str(out_dir / "lyrics_zh2.ass"))
    return zh2


def run_song(slug, name):
    from workflow_v2.paths import Concert
    c = Concert(slug)
    d = c.song_dir(c.item(name))
    zh2 = retranslate(d, d / "exp_v3")
    print(f"{name}: 二次翻译 {len(zh2)} 行")


def run_post(name):
    from workflow_v2.paths import ROOT
    d = ROOT / "posts" / name
    zh2 = retranslate(d, d / "exp_v3")
    print(f"{name}: 二次翻译 {len(zh2)} 行")


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "post":
        run_post(sys.argv[2])
    else:
        run_song(sys.argv[2], sys.argv[3])
