# -*- coding: utf-8 -*-
"""选注释词流程（song_note_workflow）：画面顶部「原词：解释」注释，从翻译流程里单独拆出来。

在翻译定稿（song_translation_workflow 第 5 步审校）之后跑，输入：每行原文 + 中文 v2 + 歌曲理解 + 歌名歌手。

    第 1 步 找候选词：逐行找可能需要注释的词，标类别（专有名词 / 真实人物事件 / 文化典故梗 / 双关），写明观众可能不懂什么
    第 2 步 筛选：程序规则去掉演唱者本人和这首歌本身、同一个词只留第一次出现；
                 独立判断「普通中国观众看了中文译文能懂这句吗」，能懂的去掉
    第 3 步 写注释：「原词：解释」，≤ 30 字，第三人称，人物第一次出现交代和歌手的关系
    第 4 步 事实核查：逐条核对，不确定或有错的去掉（宁可不注，也不注错）
    第 5 步 定数量：按重要程度最多 6 条；一条都不剩也可以
    最后：你定的注释（歌曲目录 zh_notes.json）覆盖（在 song_translation_workflow.build_outputs 里）
输出 translation/notes.json：每个候选词保留 / 去掉、原因；final = {行号: 注释}

全部用 deepseek-flash（思考 high），结果按输入缓存（translation/cache.json 里的 note_* 步骤）。
"""

import json
import re

from .song_translation_workflow import _norm, cached_ask

STEP_VERSION = {"note_candidates": "2", "note_judge": "3", "note_write": "2", "note_check": "1"}
MAX_NOTES = 6
CATS = ["专有名词", "真实人物事件", "文化典故梗", "双关"]

P_CAND = """你是字幕组的注释编辑。下面是一首歌的字幕（每行有行号、原文、中文译文）和「歌曲理解」。
逐行找出**可能**需要在画面顶部加注释的词或短语，只找这四类：
- 专有名词：人名、地名、品牌、作品、机构
- 真实人物事件：歌词影射的真实的人、事、年份、数字
- 文化典故梗：典故、传说、电影 / 文学作品、网络梗
- 双关：一个词有两层意思，中文译文只能保留一层
不要找：普通词的词义、语法、「这里指什么」、比喻本身、演唱者本人和这首歌本身。
  你（用户）明确否掉过的例子：「home：在此指两人共处的地方」「アルバム：指相册，不是音乐专辑」「レター過ぎ：letter 与すぎ组合」
  「colombiana：夏奇拉是哥伦比亚人」「Shakira：哥伦比亚流行天后」——词义、语法、「这里指什么」、歌手本人，一律不注
输出 JSON：{"candidates": [{"line": 行号, "term": "原文里的词（保留原写法）", "category": "四类之一", "unknown": "普通中国观众可能不懂的是什么"}]}"""

P_JUDGE = """你代表一个普通的中国观众（不懂外语、对欧美 / 日本娱乐圈只知道最有名的人和事）。
下面每一项是一句歌词的中文译文，以及一个候选注释词。判断标准**不是「字面读不读得懂」**，而是：
**不知道这个背景，会不会错过这句真正在说的事**——影射的真实人物 / 事件、双关的另一层意思、作品 / 典故带来的含义。
- 会错过 → need = true，给重要程度 importance（1~5，5 最重要：整句的笑点 / 狠话就靠它）
  例：「两个 22 岁的」影射新女友的年龄；「西班牙税务局追着债」影射夏奇拉的逃税案；「法拉利换雷诺」里 Twingo 是雷诺最便宜的小车
- 不会错过 → need = false：只是词义 / 语法 / 「这里指什么」；普通常识（底特律、食品券、婆婆）；中文已经把背景交代清楚了
  你（用户）明确否掉过的例子：「home：在此指两人共处的地方」「アルバム：指相册，不是音乐专辑」「レター過ぎ：letter 与すぎ组合」
  「colombiana：夏奇拉是哥伦比亚人」「Shakira：哥伦比亚流行天后」——词义、语法、「这里指什么」、歌手本人，一律不注
输出 JSON：{"items": [{"id": 编号, "need": true/false, "importance": 1~5, "reason": "一句话"}]}"""

P_WRITE = """你是字幕组的注释编辑。为下面每个词写一条画面顶部的注释：
- 格式「原词：解释」，原词保留原文写法，冒号后一句事实说明，整条不超过 30 个字
- 只陈述事实（谁、什么事、哪年、具体数字、两层意思各是什么），不评价、不解释比喻、不复述歌词、不加「注：」
- 不写「非 X」「不是 X」这种否定说明，直接说它是什么、背后是什么事
  差：「Hacienda：西班牙税务局，非『庄园』」  好：「Hacienda：西班牙税务局，曾指控夏奇拉逃税 1450 万欧元」
- **同一件事只写一条**：几个词讲的是同一个人、同一个事实（如「dos de 22」和「veintidós」都在说新女友的年龄），
  只给最能说明问题的那一个写，其余的 note 给空字符串
- 第三人称客观叙述，不受歌词译文的称呼影响（译文里自称「姐」，注释里写「夏奇拉」）
- 人物第一次出现交代和歌手的关系：「夏奇拉前男友皮克……」「皮克新女友克拉拉……」
  好：「campeón：夏奇拉前男友皮克是 2010 年世界杯冠军西班牙队主力」「Twingo：雷诺的廉价小型车，和法拉利对比」
输出 JSON：{"notes": [{"id": 编号, "note": "原词：解释"}]}"""

P_CHECK = """你是严格的事实核查编辑。逐条核对下面的注释：
- 事实（人物关系、年份、数字、事件、作品）是否准确
- 你不确定的，算「不确定」
输出 JSON：{"items": [{"id": 编号, "ok": true/false, "problem": "有错 / 不确定时说明"}]}
只有确定无误的才给 ok = true。"""


def _ask(cache, step, prompt, payload, label, key_field):
    from . import song_translation_workflow as W
    W.STEP_VERSION.setdefault(step, STEP_VERSION[step])
    return cached_ask(cache, step, prompt, json.dumps(payload, ensure_ascii=False), label,
                      check=lambda r: isinstance(r, dict) and isinstance(r.get(key_field), list))


def select_notes(cache, units, brief, title):
    """返回 (final {行号: 注释}, log [每个候选词的去向])。"""
    lines = [{"line": u["i"], "orig": u["orig"], "zh": u.get("v2", "")} for u in units if u["type"] not in ("语气词",)]
    by_line = {u["i"]: u for u in units}
    ctx = {k: brief.get(k) for k in ("theme", "voice", "notes")}
    # 第 1 步 候选
    cands = _ask(cache, "note_candidates", P_CAND, {"歌曲": title, "歌曲理解": ctx, "字幕": lines}, "注释·找候选", "candidates")["candidates"]
    log, seen = [], set()
    # 第 2 步 筛选：程序规则
    who = {_norm(x) for x in re.findall(r"[^\W\d_]+(?:\s+[^\W\d_]+)*", re.sub(r"《[^》]*》", " ", title or ""))}
    song = _norm(re.search(r"《([^》]*)》", title or "").group(1)) if re.search(r"《([^》]*)》", title or "") else ""
    kept = []
    for c in cands:
        if not isinstance(c.get("line"), int) or c["line"] not in by_line or not c.get("term"):
            continue
        t = _norm(c["term"])
        entry = {"line": c["line"], "term": c["term"], "category": c.get("category", ""), "unknown": c.get("unknown", "")}
        if c.get("category") not in CATS:
            entry["drop"] = "不在四类里"
        elif t in seen:
            entry["drop"] = "同一个词前面已经有了"
        elif t and (t in who or (song and (t in song or song in t)) or any(t and t in w for w in who)):
            entry["drop"] = "演唱者本人 / 这首歌本身"
        log.append(entry)
        if "drop" not in entry:
            seen.add(t)
            kept.append(entry)
    # 第 2 步 筛选：观众看中文能不能懂（独立判断）
    if kept:
        items = [{"id": i, "中文译文": by_line[e["line"]].get("v2", ""), "候选词": e["term"], "类别": e["category"]}
                 for i, e in enumerate(kept)]
        res = _ask(cache, "note_judge", P_JUDGE, {"items": items}, "注释·判断需不需要", "items")["items"]
        verdict = {x.get("id"): x for x in res}
        nxt = []
        for i, e in enumerate(kept):
            v = verdict.get(i, {})
            if not v.get("need"):
                e["drop"] = "观众看中文就懂：" + str(v.get("reason", ""))
            else:
                e["importance"] = int(v.get("importance") or 1)
                nxt.append(e)
        kept = nxt
    # 第 3 步 写注释
    if kept:
        items = [{"id": i, "原词": e["term"], "所在歌词": by_line[e["line"]]["orig"], "中文译文": by_line[e["line"]].get("v2", ""),
                  "类别": e["category"], "观众不懂的": e["unknown"]} for i, e in enumerate(kept)]
        res = _ask(cache, "note_write", P_WRITE, {"歌曲": title, "歌曲理解": ctx, "items": items}, "注释·写", "notes")["notes"]
        text = {x.get("id"): str(x.get("note", "")).strip() for x in res}
        for i, e in enumerate(kept):
            e["note"] = re.sub(r"^注[:：]\s*", "", text.get(i, ""))
            if not e["note"] or len(e["note"]) > 34:
                e["drop"] = "没写出来或太长"
        kept = [e for e in kept if "drop" not in e]
    # 第 4 步 事实核查
    if kept:
        items = [{"id": i, "注释": e["note"], "所在歌词": by_line[e["line"]]["orig"]} for i, e in enumerate(kept)]
        res = _ask(cache, "note_check", P_CHECK, {"歌曲": title, "items": items}, "注释·核查", "items")["items"]
        ok = {x.get("id"): x for x in res}
        for i, e in enumerate(kept):
            if not ok.get(i, {}).get("ok"):
                e["drop"] = "事实核查没通过：" + str(ok.get(i, {}).get("problem", "没有核查结果"))
        kept = [e for e in kept if "drop" not in e]
    # 第 5 步 定数量
    kept.sort(key=lambda e: -e.get("importance", 1))
    for e in kept[MAX_NOTES:]:
        e["drop"] = f"超过 {MAX_NOTES} 条，重要程度靠后"
    final = {e["line"]: e["note"] for e in kept[:MAX_NOTES]}
    return final, log
