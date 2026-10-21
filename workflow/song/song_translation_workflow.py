# -*- coding: utf-8 -*-
"""歌曲字幕翻译 workflow（song_translation_workflow）。方案见 docs/design/song_translation_workflow.md。

    第 0 步 整理：每行标类型（歌词 / 讲话 / 现场即兴 / 纯语气词）；一句话切成几行的合成一组；副歌只翻一次
    第 1 步 歌曲理解：主题、谁对谁说、语气、核心句、难点表、专名表（每首一次，按 Genius 全文缓存）
    第 2 步 术语表：你定稿的句子（只这首，歌曲目录 zh_fixed.json）> 本首风格要求（zh_style.json，如自称用「姐」）
            > 本首难点 / 专名 > 全局规则和专名（glossary.json）
    第 3 步 初译（准确）→ 中文 v1
    第 4 步 润色（表现力）→ 中文 v2（视频默认用这版）
    顶部注释（「原词：解释」）：单独的选注释词流程 song_note_workflow，在审校之后跑
    第 5 步 审校：另一次独立调用挑错；发现的问题（包括意思上的）自动改
    第 6 步 定稿：你定稿的句子替换、纯语气词留空、去句号、歌词加 ♪
    输出：subs/lyrics.ass（中文 v1）、subs/lyrics_literal.ass（中文 v2），两份都带片头歌名署名和顶部注释；
          subs/translation/result.json（每行 原文 / 类型 / v1 / v2 / 审校意见 / 是否定稿 / 注释），审核页读它

全部用 deepseek-flash（思考 high）。

    .venv/bin/python -m workflow.song.song_translation_workflow song shakira_madrid_2026 37_bzrp_music_sessions_53
    .venv/bin/python -m workflow.song.song_translation_workflow post lose_yourself_2009
    .venv/bin/python -m workflow.song.song_translation_workflow poetic song lorde_acl2026 05_shapeshifter   # 加诗意版（中文 v3）
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workflow"))

MODEL = "deepseek-flash"
EFFORT = "high"
# 每一步各自的版本：改了哪一步的提示词，只把那一步的版本加一（它后面依赖它的步骤会因为输入变了自动重跑）
STEP_VERSION = {"brief": "3", "draft": "3", "polish": "3", "review": "7", "garbage": "3", "poetic": "5", "title": "1"}
GLOSSARY = Path(__file__).with_name("glossary.json")
MAX_ZH = 18              # 中文 v2 每行最多字数（字幕可读）
GARBAGE_KEEP = 68        # 歌词行识别文字和歌词读音相似度（partial）≥ 这个：唱走样了，不当幻听（实测走样 70~100，幻听 44~60）
NOTE_MAX = 28

INTERJ = re.compile(r"^(?:\W*\b(?:oh+|ooh+|o+|yeah|yeh|ah+|a+|uh+|huh|eh+|ey|ay+|aye|woah|whoa|hey|na|la|mm+|hmm|ha|woo|oe|ole)\b\W*)+$", re.I)
END = re.compile(r"[.!?…。？！]$")

COMMON = """通用要求：
- 专有名词用中国观众熟悉的通行译名，中文里不夹外文（全局术语表和本首专名表优先）
- 称呼女性不用「妞」；结巴式重复的名字按中文译名的第一个字重复（Sha-Sha-Shakira→夏-夏-夏奇拉，La-La-Latinas→拉拉拉丁女孩）
- 俚语、黑话、双关、比喻：按「难点表」译出它在这首歌里的所指，不保留字面意象（gato 指人时不是「猫」）
- 句中的语气词（oh / yeah / ah / uh / hey）不要译成「哦 / 耶 / 啊」，直接省略；纯语气词的行输出空字符串
- 「讲话」类型的行是歌手对观众说的话，用自然口语，不写成歌词腔
- 「现场即兴」类型是现场改的词或临时加的内容（不在原版歌词里），照听到的意思翻
- 「已定译法」里的句子照抄（用户亲自定稿的），其它句子的语气和它保持一致
- 「本首风格要求」必须遵守（例：自称一律用「姐」）
- 同一句歌词（副歌）每次出现译法一样
- 先看「歌曲理解」里的背景再翻：看似夸张、反讽的说法可能是真实事件（皮克真是世界杯冠军，不是「自封冠军」）"""

P_BRIEF = """你是资深歌词译者。先通读整首歌词，为后面的翻译写一份「歌曲理解」，输出 JSON：
{"theme": "这首歌讲什么，2~3 句",
 "voice": "谁对谁说（叙事视角、人物关系）",
 "tone": "语气 / 情绪",
 "core_lines": ["核心句原文：歌名所在的句子、副歌主旨句、宣言式的金句，3~6 句"],
 "notes": [{"src": "难点原文片段", "means": "在这首歌里指什么（俚语 / 黑话 / 双关 / 比喻 / 典故 / 真实人物事件）", "zh": "建议译法", "needs_note": true}],
 "names": {"原文专名": "中文译名（人名、地名、品牌、机构）"}}
- needs_note：翻译一句话讲不透、观众需要背景知识才懂的（双关、真实人物事件、文化梗），为 true；翻译能说清的为 false
- **真实人物、事件写清背景**：谁、什么事、哪一年、具体数字。歌词里看似夸张的说法可能是真的：
  例：BZRP「Tanto que te las das de campeón」——皮克真是 2010 年世界杯冠军西班牙队主力，讽刺他总拿冠军身份摆架子，不是「自封冠军」
- 用中文写；不要逐句翻译歌词"""

P_DRAFT = """你是专业的歌词译者。下面是一首歌按时间顺序排好的字幕，分成若干组（一组是一句完整的话，可能被切成几行）。
请逐组翻译成简体中文，**准确第一**：意思不漏、不加、不错；按组理解、按行输出（一行原文对应一行中文，可以在组内相邻行之间调整语序）。
""" + COMMON + """
输出 JSON：{"groups": [{"id": 组号, "zh": ["第一行中文", "第二行中文", ...]}, ...]}，每组 zh 的行数和原文完全一致；不要加 ♪，不要解释。"""

P_POLISH = """你是顶尖的中文歌词译者和作词人。下面是一首歌的字幕（按组），每行有原文和准确的初译（v1）。
请以初译为底稿，重写一版中文 v2：
- **更有画面感和表现力**：用具体的意象、动作、情绪代替平淡的直译，读起来像一首好的中文歌词；可以用对仗、押韵、节奏感，不堆砌辞藻
- **核心句要有高度**：「歌曲理解」里列出的核心句，译出背后的态度和主张，像一句能被记住、被转发的金句，可以用感叹号
  （例：「Las mujeres ya no lloran, las mujeres facturan」→「女人不再流泪，女人要为自己买单！」）
- **不能改变意思**：不加原文没有的情节和意思（不要给语气词编内容，「Ah-ah-ah, you're lookin' for」不能译成「念念不忘，你在找」）
- 每行简短，一般不超过 18 个汉字
""" + COMMON + """
输出 JSON：{"groups": [{"id": 组号, "zh": [...]}, ...]}，每组行数和原文一致；不要加 ♪，不要解释。"""

P_POETIC = """你是当代中文诗人。下面是一首歌的字幕（按组）。请直接从原文出发，把它写成一首中文诗（诗意版）。
要的是诗行，不是翻译句。示例（和这首歌无关，只看「直译」和「诗意」差在哪）：
  I keep my secrets in the dark          直译：我把秘密藏在黑暗里           诗意：秘密，都交给了夜
  You were the one who made me feel alive 直译：你是那个让我觉得自己活着的人  诗意：是你，让我活过来
  We danced until the morning came        直译：我们一直跳舞跳到早上         诗意：我们跳着，跳到天光
- 凝练：省掉多余的「的」「在」「了」「那个」，语序可以倒装、重心放到行尾；一行一个画面或一个动作
- 节奏：原文怎么重复，中文就怎么重复，不要缩写合并（I've been the ice, I've been the flame → 「我曾是寒冰，我曾是火焰」，
  不要写成「我曾是冰，也曾是火」）；排比、对举写出对称；副歌像副歌一样回环
- 画面感：意象用有画面、有温度的双音词，不用单个字（冰→寒冰、火→火焰、手→掌心）；在原文意象的范围里给它颜色、温度、质地、动作，
  让人看得见；不加原文没有的情节
- 措辞有质感：可以少量用「曾、亦、已、独、皆」点缀，整体是现代诗，不是文言
- 不改意思、不编内容：每行写的必须是原文这一行说的事（可以换说法、换角度），不加原文没有的情节和情绪
- 不堆砌辞藻：不用「璀璨、斑驳、殇、阑珊、缱绻、氤氲」这类空泛的词；少用成语
- 保持歌曲的语气（见「歌曲理解」）：冷峻的不写甜，直白的不写酸
- 每行一般不超过 14 个汉字；纯语气词行输出空字符串；「讲话」「现场即兴」行照意思用自然口语，不写成诗
""" + COMMON + """
输出 JSON：{"groups": [{"id": 组号, "zh": [...]}, ...]}，每组行数和原文一致；不要加 ♪，不要解释。"""

P_TITLE = """你是资深的中文歌词译者，整首歌词已经翻完，现在定这首歌的中文歌名。
下面有原文歌名、「歌曲理解」、歌词里出现歌名（或歌名关键词）的句子和它们已经定好的中文译法。
- 这首歌在中文世界有广为流传的通行译名（唱片公司官方中文名、主流音乐平台通用的名字）时，用通行译名
- 没有通行译名：歌名的中文要和歌词里同一个词的译法一致（歌词里 royals 译成「皇室」，歌名就不要另译成「贵族」）；
  译出这个词在这首歌里的真实含义，不要按字典第一个义项直译（liability 在歌里指「累赘 / 负担」，不是会计上的「负债」）
- 像一个歌名：简短（一般 2～6 个字），不加书名号；原名是人名 / 缩写 / 拟声、或者节目名带编号（BZRP Music Sessions #53），输出原文
输出 JSON：{"zh": "中文歌名", "why": "一句话"}"""

P_GARBAGE = """下面是一首歌现场字幕里不太确定的行，每行有「识别」（语音识别听到的文字）；歌词行还有对应的「歌词」。
现场有人群声、混响，识别有时会听出**没有意义的幻听**：乱码、不成句的词串、零散字母、和这首歌语言无关的别的语言词串
（如「Like the name if apa if any if」「canada Tak a c e t three i o two u Gimana mana em gimana」「Aku bersama Jay」）。
找出「识别」是这种幻听的行。
- 识别文字本身是有意义的词句，即使和歌词不一样（观众合唱、口音、听走样：「La suegra y la vecina」「Más dura más dura」），不算
- 正常的讲话（哪怕很短、口语化：「Thank you」「Madrid!」「Everybody」），不算
每一项是一段（讲话可能是连续几行，用「 / 」隔开）；整段是幻听才算。
输出 JSON：{"drop": [{"id": 编号, "reason": "一句话"}]}，没有就给空数组。"""

P_REVIEW = """你是严格的字幕审校。逐行对照原文、初译（v1）、润色稿（v2）和「歌曲理解」，找出 v2 的问题并直接给出改好的 v2：
- 意思跑偏、和原文不符
- 加了原文没有的意思（包括给语气词编内容）
- 俚语 / 比喻按字面翻（如把指人的 gato 译成「猫」）
- 同一句歌词前后译法不一致
- 太长（超过 18 个汉字）
- 中文里夹着外文、用了「妞」、语气词译成「哦 / 耶 / 啊」
- 讲话写成了歌词腔
""" + COMMON + """
输出 JSON：{"issues": [{"line": 行号, "type": "问题类型", "problem": "一句话说明", "fix": "改好的 v2"}],
}
没有问题就给空数组。"""


# ---------------------------------------------------------------- 工具

def _norm(t):
    return re.sub(r"[^\w]+", " ", (t or "").lower()).strip()


def _h(*xs):
    return hashlib.sha1(json.dumps(xs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


import threading
CACHE_LOCK = threading.Lock()


class Cache:
    """translation/cache.json：{步骤: {输入哈希: 输出}}；输入哈希包含提示词、提示词版本、模型。"""

    def __init__(self, path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def get(self, step, key):
        return self.data.get(step, {}).get(key)

    def put(self, step, key, val):
        with CACHE_LOCK:   # 长歌分批同时发，几个线程会同时写缓存
            self.data.setdefault(step, {})[key] = val
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))


def ask(prompt, user, label):
    import llm
    os.environ["TRANSLATE_MODEL"] = MODEL
    return llm.chat_json(prompt, user, label=label, effort=EFFORT, temperature=TEMPERATURE)


TEMPERATURE = 0.3   # 翻译偏稳；诗意版那一步临时调高


TIMES = {}   # 每一步花了多少秒（这次运行）


def cached_ask(cache, step, prompt, payload, label, check=None):
    """缓存键只看这一步自己的版本、提示词、输入：前面的步骤结果没变，后面的步骤就不会重跑。"""
    import time
    base = step.split("_")[0]
    key = _h(STEP_VERSION.get(base, "1"), MODEL, EFFORT, prompt, payload)
    got = cache.get(step, key)
    if got is not None:
        return got
    user = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    t0 = time.time()
    for _ in range(3):
        res = ask(prompt, user, label)
        TIMES[label] = TIMES.get(label, 0) + time.time() - t0
        if check is None or check(res):
            cache.put(step, key, res)
            return res
        print(f"  {label} 返回格式不对，重试", flush=True)
    raise RuntimeError(f"{label} 连续三次格式不对")


# ---------------------------------------------------------------- 第 0 步 整理

def load_units(out_dir):
    """字幕（lyrics.srt + speech.srt）→ 按时间的每一行：{start, end, orig, type}；类型参考 lines.json 的判定。"""
    import pysubs2
    rows = json.loads((out_dir / "lines.json").read_text()) if (out_dir / "lines.json").exists() else []
    info = {(r["start_ms"], r["text"]): r for r in rows if not r.get("removed")}
    units = []
    for f, sp in (("lyrics.srt", False), ("speech.srt", True)):
        p = out_dir / f
        if not p.exists():
            continue
        for e in pysubs2.load(str(p)).events:
            orig = re.sub(r"\s+", " ", e.plaintext).strip()
            if not orig:
                continue
            r = info.get((e.start, orig), {})
            typ = "讲话" if sp else ("现场即兴" if r.get("verdict") == "live" else "歌词")
            if INTERJ.match(orig):
                typ = "语气词"
            units.append({"start": e.start, "end": e.end, "orig": orig, "type": typ, "heard": r.get("qwen", ""),
                          "anchor": bool(r.get("anchor")), "verdict": r.get("verdict", "")})
    units.sort(key=lambda u: u["start"])
    for i, u in enumerate(units):
        u["i"] = i
    return units


def make_groups(units):
    """一句话被切成几行的合成一组：同类型、相邻两行间隔 ≤ 0.8 s、上一行没有句末标点，最多 4 行。"""
    groups, cur = [], []
    for u in units:
        if u["type"] == "语气词":
            if cur:
                groups.append(cur)
            cur = []
            continue
        if cur and (u["type"] != cur[-1]["type"] or u["start"] - cur[-1]["end"] > 800 or END.search(cur[-1]["orig"])
                    or len(cur) >= 4):
            groups.append(cur)
            cur = []
        cur.append(u)
    if cur:
        groups.append(cur)
    return groups


def unique_groups(groups):
    """同样的组（副歌）只翻一次：key = 类型 + 每行原文。返回 [(key, 组)] 和 组 → key。"""
    seen, uniq = {}, []
    for g in groups:
        k = (g[0]["type"],) + tuple(_norm(u["orig"]) for u in g)
        if k not in seen:
            seen[k] = len(uniq)
            uniq.append(g)
    return uniq, seen


# ---------------------------------------------------------------- 第 1、2 步

def song_brief(cache, lyrics, title):
    payload = (f"歌曲：{title}\n\n" if title else "") + "\n".join(lyrics)
    return cached_ask(cache, "brief", P_BRIEF, payload, "歌曲理解",
                      check=lambda r: isinstance(r, dict) and "notes" in r)


def glossary_for(brief, fixed, style):
    g = json.loads(GLOSSARY.read_text()) if GLOSSARY.exists() else {}
    names = dict(brief.get("names") or {})
    names.update(g.get("names", {}))   # 全局专名优先
    return {"全局规则": g.get("rules", []), "本首风格要求": style, "专名": names,
            "难点": [{k: n.get(k) for k in ("src", "means", "zh")} for n in brief.get("notes", [])],
            "已定译法": fixed}


def context_text(brief, gloss):
    return ("歌曲理解：\n" + json.dumps({k: brief.get(k) for k in ("theme", "voice", "tone", "core_lines")}, ensure_ascii=False)
            + "\n\n术语表：\n" + json.dumps(gloss, ensure_ascii=False) + "\n\n")


# ---------------------------------------------------------------- 第 3、4 步

def by_groups(cache, step, prompt, uniq, ctx, label, extra=None):
    """按组翻：输入 [{id, type, lines[, v1]}]，输出每组的中文行；行数不对的组单独重试。"""
    out = {}
    payload = [{"id": i, "type": g[0]["type"], "lines": [u["orig"] for u in g],
                **({"v1": extra[i]} if extra else {})} for i, g in enumerate(uniq)]

    def ok(res):
        return isinstance(res, dict) and isinstance(res.get("groups"), list)
    from concurrent.futures import ThreadPoolExecutor
    batches = [payload[i:i + 20] for i in range(0, len(payload), 20)]   # 长歌分批（每批 20 组，同时发），整首的歌曲理解和术语表每批都带
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda b: cached_ask(cache, step, prompt, ctx + json.dumps(b, ensure_ascii=False), label, check=ok),
                              batches))
    for res in results:
        for gr in res["groups"]:
            gid = gr.get("id")
            if isinstance(gid, int) and 0 <= gid < len(uniq) and len(gr.get("zh", [])) == len(uniq[gid]):
                out[gid] = [str(z).strip() for z in gr["zh"]]
    miss = [i for i in range(len(uniq)) if i not in out]
    if miss:   # 行数不对 / 漏掉的组：单独再翻一次
        batch = [p for p in payload if p["id"] in miss]
        res = cached_ask(cache, step + "_retry", prompt, ctx + json.dumps(batch, ensure_ascii=False), label + "（补）", check=ok)
        for gr in res["groups"]:
            gid = gr.get("id")
            if gid in miss and len(gr.get("zh", [])) == len(uniq[gid]):
                out[gid] = [str(z).strip() for z in gr["zh"]]
    for i in range(len(uniq)):
        out.setdefault(i, [""] * len(uniq[i]))
    return out


# ---------------------------------------------------------------- 主流程

def translate(d, out_dir, lyrics, title):
    from translate_ass import translate_title
    tdir = out_dir / "translation"
    cache = Cache(tdir / "cache.json")
    units = load_units(out_dir)
    if not units:
        return None
    fixed_file = d / "zh_fixed.json"
    fixed = json.loads(fixed_file.read_text()) if fixed_file.exists() else {}
    fixed_here = {k: v for k, v in fixed.items() if any(_norm(u["orig"]) == _norm(k) for u in units)}

    # 第 0 步
    groups = make_groups(units)
    uniq, gkey = unique_groups(groups)
    # 第 1、2 步
    brief = song_brief(cache, lyrics, title)
    style_file = d / "zh_style.json"
    style = json.loads(style_file.read_text()).get("rules", []) if style_file.exists() else []
    gloss = glossary_for(brief, fixed_here, style)
    ctx = context_text(brief, gloss)
    # 第 3 步 初译
    v1 = by_groups(cache, "draft", P_DRAFT, uniq, ctx, "初译")
    # 第 4 步 润色
    v2 = by_groups(cache, "polish", P_POLISH, uniq, ctx, "润色", extra=v1)

    # 展开到每一行（同样的组共用译文）
    for g in groups:
        gi = gkey[(g[0]["type"],) + tuple(_norm(u["orig"]) for u in g)]
        for u, a, b in zip(g, v1[gi], v2[gi]):
            u["v1"], u["v2"] = a, b
    for u in units:
        u.setdefault("v1", "")
        u.setdefault("v2", "")
        u["issues"] = []
        u["locked"] = False

    lines = [{"line": u["i"], "type": u["type"], "orig": u["orig"], "v1": u["v1"], "v2": u["v2"]} for u in units
             if u["type"] != "语气词"]
    notes = {}
    # 第 5 步 审校（自动改，包括意思上的问题）
    # 审校按 40 行一批同时发（长歌整首一次要 40 多秒）；每批带上前后各 3 行做上下文
    from concurrent.futures import ThreadPoolExecutor
    chunks = [(i, min(len(lines), i + 40)) for i in range(0, len(lines), 40)]

    def review_chunk(ab):
        a, b = ab
        part = lines[max(0, a - 3):b + 3]
        ids = {x["line"] for x in lines[a:b]}
        return cached_ask(cache, "review", P_REVIEW,
                          ctx + "只审这些行号：" + json.dumps(sorted(ids)) + "（前后几行是上下文）\n" +
                          json.dumps({"字幕": part}, ensure_ascii=False), "审校",
                          check=lambda r: isinstance(r, dict) and isinstance(r.get("issues"), list))
    with ThreadPoolExecutor(max_workers=4) as ex:
        parts = list(ex.map(review_chunk, chunks))
    res = {"issues": [x for p in parts for x in p.get("issues", [])]}
    for it in res.get("issues", []):
        i = it.get("line")
        if not isinstance(i, int) or not 0 <= i < len(units) or not it.get("fix"):
            continue
        u = units[i]
        old = u["v2"]
        # 同一句歌词（副歌）的其它出现一起改，保持一致
        for w in units:
            if _norm(w["orig"]) == _norm(u["orig"]) and w["type"] == u["type"]:
                w["issues"].append({"type": it.get("type", ""), "problem": it.get("problem", ""), "from": old, "fix": it["fix"]})
                w["v2"] = str(it["fix"]).strip()
    # 讲话 / 现场即兴的行（Genius 里没有、来自识别）：没有意义的幻听（人群声里识别出的乱码、不成句）不出字幕
    # 幻听检查：识别出来的文字本身没有意义（人群声里的乱码、别的语言的词串）的行不出字幕
    # - 讲话 / 现场即兴：连续的（间隔 ≤ 2 s）算一段，整段一起判断（单看一行「sound like」像正常的话，其实是一段幻听里的）
    # - 不是锚点的歌词行：识别文字和这句歌词读音有点像（≥ GARBAGE_KEEP）的，是唱走样了，一律保留，不送去判断
    from rapidfuzz import fuzz
    from .run import key_of
    segs, cur = [], []
    for u in units:
        if u["type"] in ("讲话", "现场即兴"):
            if cur and (u["start"] - cur[-1]["end"] > 2000 or u["type"] != cur[-1]["type"]):
                segs.append(cur)
                cur = []
            cur.append(u)
        elif cur:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    items, members = [], {}
    for g in segs:
        gid = len(items)
        items.append({"id": gid, "type": g[0]["type"], "识别": " / ".join(u.get("heard") or u["orig"] for u in g)})
        members[gid] = g
    for u in units:
        h = u.get("heard") or ""
        if u["type"] == "歌词" and not u.get("anchor") and u.get("verdict") != "crowd" and h and h not in ("（没听到）", "（观众合唱）") \
                and fuzz.partial_ratio(key_of(h), key_of(u["orig"])) < GARBAGE_KEEP:
            gid = len(items)
            items.append({"id": gid, "type": "歌词", "识别": h, "歌词": u["orig"]})
            members[gid] = [u]
    if items:
        res = cached_ask(cache, "garbage", P_GARBAGE, json.dumps({"歌曲": title, "items": items}, ensure_ascii=False), "幻听检查",
                         check=lambda r: isinstance(r, dict) and isinstance(r.get("drop"), list))
        for x in res["drop"]:
            if isinstance(x, dict) and x.get("id") in members:
                for u in members[x["id"]]:
                    u["dropped"] = "没有意义的识别结果（多半是人群声里的幻听）：" + str(x.get("reason", ""))
    # 顶部注释：单独的选注释词流程（song_note_workflow），在审校之后、用定稿的中文判断「观众看中文能不能懂」
    from .song_note_workflow import select_notes
    notes, note_log = select_notes(cache, units, brief, title)
    (tdir / "notes.json").write_text(json.dumps({"final": {str(k): v for k, v in notes.items()}, "candidates": note_log},
                                                ensure_ascii=False, indent=1))

    # 片头歌名
    zc_path = d / "zh_cache.json"
    zc = json.loads(zc_path.read_text()) if zc_path.exists() else {}
    os.environ["TRANSLATE_MODEL"] = MODEL
    title_zh = translate_title(title, zc) if title else None
    zc_path.write_text(json.dumps(zc, ensure_ascii=False, indent=1))

    result = {"model": MODEL, "effort": EFFORT, "version": STEP_VERSION, "seconds": {k: round(v, 1) for k, v in TIMES.items()}, "title": title, "title_zh": title_zh, "brief": brief,
              "units": units, "notes": {str(k): v for k, v in notes.items()}}
    # 第 7 步 歌名：整首翻完之后再定，和歌词里同一个词的译法一致
    song_title(cache, result)
    (tdir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    build_outputs(d, out_dir)
    return result


def song_title(cache, R):
    """中文歌名（整首翻完之后）：歌词里出现歌名的句子怎么译的，歌名就跟着；有通行译名用通行译名。
    只改《》里的歌名，中文歌手名不动（R["title_zh"] 形如「《中文歌名》 中文歌手」）。"""
    title, old = R.get("title") or "", R.get("title_zh") or ""
    m = re.search(r"《([^》]*)》", title)
    if not m:
        return old
    name = m.group(1)
    keys = [w for w in re.findall(r"[^\W\d_]{3,}", name.lower())]
    hits = [{"原文": u["orig"], "中文": u.get("v2_final") or u.get("v2", "")} for u in R["units"]
            if u.get("type") != "讲话" and any(k in u["orig"].lower() for k in keys)]
    seen, uniq = set(), []
    for h in hits:
        if h["原文"] not in seen:
            seen.add(h["原文"])
            uniq.append(h)
    brief = R.get("brief") or {}
    payload = json.dumps({"歌名": name, "整行": title, "歌曲理解": {k: brief.get(k) for k in ("theme", "voice", "tone", "core_lines")},
                          "歌词里出现歌名的句子": uniq[:12]}, ensure_ascii=False)
    res = cached_ask(cache, "title", P_TITLE, payload, "歌名", check=lambda r: isinstance(r, dict) and str(r.get("zh", "")).strip())
    zh = str(res["zh"]).strip().strip("《》")
    new = re.sub(r"《[^》]*》", f"《{zh}》", old) if "《" in old else f"《{zh}》 {old}".strip()
    R["title_zh"], R["title_why"] = new, res.get("why", "")
    return new


# ---------------------------------------------------------------- 第 6 步 定稿 + 写字幕文件（审核页改了以后也只重跑这一步）

def no_dash(z):
    """中文里不要破折号（——、—、–、--）：句末的删掉，句中的换成逗号；结巴式的单个连字符（夏-夏-夏奇拉）保留。"""
    z = re.sub(r"\s*(?:[—–]+|-{2,})\s*$", "", z.strip())
    z = re.sub(r"\s*(?:[—–]+|-{2,})\s*", "，", z)
    z = re.sub(r"[，,]{2,}", "，", z)
    return re.sub(r"^[，,]\s*", "", z).strip()


def finalize(d, units):
    fixed_file = d / "zh_fixed.json"
    fixed = json.loads(fixed_file.read_text()) if fixed_file.exists() else {}
    fx = {_norm(k): v for k, v in fixed.items()}
    for u in units:
        u["locked"] = _norm(u["orig"]) in fx
        if u["locked"]:
            u["v2_final"] = fx[_norm(u["orig"])]
        else:
            u["v2_final"] = u["v2"]
        if u.get("v3") is not None:   # 诗意版：讲话沿用 v2 的口语
            u["v3_final"] = u["v2_final"] if u["type"] == "讲话" else u["v3"]
        for k in ("v1", "v2_final", "v3_final"):
            if k not in u:
                continue
            z = u[k]
            if u["type"] == "语气词":
                z = ""
            z = no_dash(z)
            z = re.sub(r"[。.]$", "", z.strip())
            u[k] = z
    return units


def build_outputs(d, out_dir):
    import pysubs2
    from translate_ass import CJK_FONT, build_ass
    tdir = out_dir / "translation"
    res = json.loads((tdir / "result.json").read_text())
    units = finalize(d, res["units"])
    notes = {int(k): v for k, v in res["notes"].items()}
    # 你在审核页改 / 加 / 删的注释：歌曲目录 zh_notes.json，{原文: 注释}，空字符串 = 删掉；按原文找第一次出现的那一行
    nf = d / "zh_notes.json"
    for orig, v in (json.loads(nf.read_text()) if nf.exists() else {}).items():
        idx = next((u["i"] for u in units if _norm(u["orig"]) == _norm(orig)), None)
        if idx is None:
            continue
        for u in units:   # 同一句只在第一次出现处注
            if _norm(u["orig"]) == _norm(orig):
                notes.pop(u["i"], None)
        if v:
            notes[idx] = v
    res["final_notes"] = {str(k): v for k, v in notes.items()}
    res["units"] = units
    (tdir / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    lyr = [u for u in units if u["type"] != "讲话" and not u.get("dropped")]
    sp = [u for u in units if u["type"] == "讲话" and not u.get("dropped")]
    vers = [("v1", "v1", "lyrics.ass"), ("v2", "v2_final", "lyrics_literal.ass")]
    if any("v3_final" in u for u in units):
        vers.append(("v3", "v3_final", "lyrics_poetic.ass"))   # 诗意版
    for ver, key, fname in vers:
        subs = pysubs2.SSAFile()
        for u in lyr:
            subs.events.append(pysubs2.SSAEvent(start=u["start"], end=u["end"], text=u["orig"]))
        ass = build_ass(subs, [u[key] for u in lyr], res.get("title"), 6000, "bzrp", res.get("title_zh"),
                        sp[0]["start"] if sp else None)
        sty = ass.styles["Default"].copy()
        sty.primarycolor = pysubs2.Color(255, 214, 102)
        ass.styles["Speech"] = sty
        for u in sp:
            text = u["orig"] + (r" \N" + u[key] if u[key] and u[key] != u["orig"] else "")
            ass.events.append(pysubs2.SSAEvent(start=u["start"], end=u["end"], text=text, style="Speech"))
        # 顶部注释「原词：解释」：浅绿色半透明小字、没有描边和底色、顶住画面上边缘居中；跟着对应那句，至少 4 s
        note = ass.styles["Default"].copy()
        note.fontname, note.fontsize = CJK_FONT, 18   # 2026-10-21 从 15 调大
        note.primarycolor = pysubs2.Color(170, 235, 170, 80)      # 浅绿色，约 70% 不透明（第四个数是透明度）
        note.outlinecolor = pysubs2.Color(0, 0, 0, 255)
        note.backcolor = pysubs2.Color(0, 0, 0, 255)
        note.borderstyle, note.outline, note.shadow = 1, 0, 0   # 不要描边、不要底条
        note.alignment = pysubs2.Alignment.TOP_CENTER
        note.marginv = 2                                           # 顶住画面上边缘
        ass.styles["Note"] = note
        for i, text in sorted(notes.items()):
            u = units[i]
            ass.events.append(pysubs2.SSAEvent(start=u["start"], end=max(u["end"], u["start"] + 4000), text=text, style="Note"))
        ass.events.sort(key=lambda e: e.start)
        ass.save(str(out_dir / fname))


def poetic(d, out_dir, model=None, temperature=0.7):
    """诗意版（中文 v3）：在已有翻译结果上加一步，直接从原文写有诗意的版本（不给初译，免得照着改几个字）；不动 v1 / v2。"""
    tdir = out_dir / "translation"
    R = json.loads((tdir / "result.json").read_text())
    cache = Cache(tdir / "cache.json")
    units = R["units"]
    groups = make_groups(units)
    uniq, gkey = unique_groups(groups)
    fixed_file = d / "zh_fixed.json"
    fixed = json.loads(fixed_file.read_text()) if fixed_file.exists() else {}
    fixed_here = {k: v for k, v in fixed.items() if any(_norm(u["orig"]) == _norm(k) for u in units)}
    style_file = d / "zh_style.json"
    style = json.loads(style_file.read_text()).get("rules", []) if style_file.exists() else []
    gloss = glossary_for(R.get("brief") or {}, fixed_here, style)
    # 难点表只留「在这首歌里指什么」，去掉建议译法（不然整句照抄建议译法，写不出诗意）
    gloss["难点"] = [{k: n.get(k) for k in ("src", "means")} for n in gloss.get("难点", [])]
    ctx = context_text(R.get("brief") or {}, gloss)
    global MODEL, TEMPERATURE
    keep = (MODEL, TEMPERATURE)
    MODEL, TEMPERATURE = model or MODEL, temperature
    try:
        v3 = by_groups(cache, "poetic", P_POETIC, uniq, ctx, "诗意")   # 不给初译：给了它就照着改几个字
    finally:
        MODEL, TEMPERATURE = keep
    R["poetic_model"] = model or keep[0]
    for g in groups:
        gi = gkey[(g[0]["type"],) + tuple(_norm(u["orig"]) for u in g)]
        for u, z in zip(g, v3[gi]):
            u["v3"] = z
    for u in units:
        u.setdefault("v3", "")
    (tdir / "result.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
    build_outputs(d, out_dir)
    return R


def run_song(slug, name):
    import acoustic
    from workflow.live.paths import Concert
    from workflow.live.refine import sub_title
    c = Concert(slug)
    it = c.item(name)
    d = c.song_dir(it)
    res = translate(d, d / "subs", [t for t, _ in acoustic.section_lines(d / "lyrics.txt")], sub_title(c, it))
    report(name, res)


def run_post(name):
    from workflow.live.paths import ROOT as R
    d = R / "posts" / name
    post = json.loads((d / "post" / f"{name}.json").read_text())
    song = post.get("song") or {}
    lyrics = [l.strip() for l in (d / "lyrics.txt").read_text().splitlines() if l.strip() and not l.startswith("[")]
    res = translate(d, d / "subs", lyrics, f"《{song.get('title') or name}》 {song.get('artist') or ''}".strip())
    report(name, res)


def report(name, res):
    if not res:
        print(name, "没有字幕")
        return
    us = res["units"]
    t = res.get("seconds") or {}
    print(f"{name}: {len(us)} 行，审校改了 {sum(1 for u in us if u['issues'])} 行，顶部注释 {len(res['notes'])} 条；"
          f"耗时 {sum(t.values()):.0f}s（" + "，".join(f"{k} {v:.0f}s" for k, v in t.items()) + "；有缓存的步骤不算）", flush=True)


def run_many(specs):
    """几首一起翻（都是云端接口调用，不占本地模型）：specs = ["song:slug:name", "post:name", ...]"""
    import subprocess
    procs = []
    for sp in specs:
        args = sp.split(":")
        cmd = [sys.executable, "-m", "workflow.song.song_translation_workflow"] + (["post", args[1]] if args[0] == "post" else ["song", args[1], args[2]])
        procs.append(subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    for p in procs:
        out = p.communicate()[0]
        print([l for l in out.splitlines() if "耗时" in l or "Error" in l or "Traceback" in l][-1:] or out[-300:], flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "title":   # 只重定歌名：title song <slug> <name> / title post <name>
        if sys.argv[2] == "post":
            dd = ROOT / "posts" / sys.argv[3]
        else:
            from workflow.live.paths import Concert
            cc = Concert(sys.argv[3])
            dd = cc.song_dir(cc.item(sys.argv[4]))
        tf = dd / "subs" / "translation" / "result.json"
        RR = json.loads(tf.read_text())
        old = RR.get("title_zh")
        song_title(Cache(tf.parent / "cache.json"), RR)
        tf.write_text(json.dumps(RR, ensure_ascii=False, indent=1))
        build_outputs(dd, dd / "subs")
        print(f"{dd.name}: {old} → {RR['title_zh']}（{RR.get('title_why', '')}）")
    elif sys.argv[1] == "poetic":   # 诗意版：poetic song <slug> <name> / poetic post <name>
        if sys.argv[2] == "post":
            dd = ROOT / "posts" / sys.argv[3]
        else:
            from workflow.live.paths import Concert
            cc = Concert(sys.argv[3])
            dd = cc.song_dir(cc.item(sys.argv[4]))
        mi = sys.argv.index("--model") if "--model" in sys.argv else None
        poetic(dd, dd / "subs", model=sys.argv[mi + 1] if mi else None)
    elif sys.argv[1] == "many":
        run_many(sys.argv[2:])
    elif sys.argv[1] == "post":
        run_post(sys.argv[2])
    else:
        run_song(sys.argv[2], sys.argv[3])
