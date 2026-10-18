# -*- coding: utf-8 -*-
"""
package：每首歌的候选封面 + 投稿标题 / 介绍草稿，给审核页用。
  - 封面：v1 make_cover.py 的默认流程（正脸特写 6 张、半身 3 张、全身 3 张，共 12 张，Real-ESRGAN 高清化），
    只在这首歌的时间段里用 ffmpeg -ss 取单帧（不落地帧序列）；副标题正常字号、居中，带艺人中文名 -> songs/<nn>/covers/
  - 标题：固定格式（post_title），不让模型写
  - 介绍：v1 make_meta.py 的提示词，事实材料换成演唱会信息 + 歌单备注，歌曲介绍 + 演出介绍各 300 字左右，
    合成一段（空行分开）-> songs/<nn>/post_draft.json
"""

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .paths import ROOT, VENV_PY, read_json, write_json
from .refine import selected

PER_SHOT = "closeup=16,half=16,full=0"   # 正脸特写 16 张、半身 16 张；全身脸太小、当封面看不清人，不要
CLOSEUP_MIN = 0.14  # 脸高占画面 14% 以上算特写：转播里 22% 以上的大特写很少（GIRL LIKE ME 只有 6 帧候选），凑不够 6 张
TEXT_LIFT = 0.08   # 标题 + 副标题整体上移画面高度的 8%（0.82 -> 0.74）：底部 17% 压暗遮挡转播的推广条，字压在上面太靠下
LANG_ZH = {"es": "西班牙语", "en": "英语", "it": "意大利语", "ja": "日语", "pt": "葡萄牙语", "fr": "法语"}
COVER_RE = re.compile(r"^(closeup|half|full|cover)_(\d\d)\.jpg$")
FRAME_RE = re.compile(r"^frame_(?:(closeup|half|full)_)?(\d\d)_([\d.]+)s\.jpg$")


def cover_candidates(d):
    """covers/ 下的候选：[{id, file, file_4x3, t}]，t 是在整场里的时间（秒）。"""
    cdir = d / "covers"
    if not cdir.exists():
        return []
    times = {}
    for f in cdir.iterdir():
        m = FRAME_RE.match(f.name)
        if m:
            times[f"{m[1] or 'cover'}_{m[2]}"] = float(m[3])
    out = []
    for f in sorted(cdir.iterdir()):
        m = COVER_RE.match(f.name)
        if m:
            cid = f"{m[1]}_{m[2]}"
            f43 = cdir / f"{cid}_4x3.jpg"
            out.append({"id": cid, "file": f"covers/{f.name}", "file_4x3": f"covers/{f43.name}" if f43.exists() else None,
                        "t": times.get(cid)})
    order = {"closeup": 0, "half": 1, "full": 2, "cover": 3}   # 特写、半身、全身，按清晰度补的放最后
    return sorted(out, key=lambda x: (order.get(x["id"].split("_")[0], 9), x["id"]))


def subtitle_line(c, it):
    info = read_json(c.info)
    song = read_json(c.song_dir(it) / "song.json", {})
    langs = song.get("langs") or [song.get("lang", "en")]
    zh = info.get("artist_zh") or (read_json(c.song_dir(it) / "post_draft.json", {}).get("song") or {}).get("artist_zh")
    who = f"{zh} {info.get('artist', '')}" if zh and zh != info.get("artist") else info.get("artist", "")
    return f"{who} · 中{''.join(LANG_ZH.get(x, '外')[0] for x in langs)}字幕"


def make_covers(c, it, seg, a):
    """候选封面：make_cover 的默认流程（正脸特写 / 半身各 16 张，去掉糊的，Real-ESRGAN 高清化）。
    不再按整帧清晰度补 cover_XX：补出来的基本是全景，看不清人。"""
    import shutil
    d = c.song_dir(it)
    out = d / "covers"
    common = [VENV_PY, ROOT / "workflow" / "make_cover.py", "--name", it["name"], "--title", it["title"],
              "--subtitle", subtitle_line(c, it), "--video", c.source, "--out-dir", out, "--sub-fit", "natural",
              "--start", f"{seg['start']:.2f}", "--end", f"{seg['end']:.2f}", "--text-lift", TEXT_LIFT, "--closeup-min", CLOSEUP_MIN]
    mask = read_json(c.info).get("cover_mask_bottom")
    if mask:  # 转播画面底部的台标 / 歌名条 / 推广条：模糊压暗盖住
        common += ["--mask-bottom", str(mask)]
    if a.force and out.exists():
        shutil.rmtree(out)  # 重新挑：旧候选的文件名和时间点都不一样了，留着会混在一起
    log = d / "logs" / "v2_covers.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as fh:
        if not any(x["id"].split("_")[0] in ("closeup", "half", "full") for x in cover_candidates(d)):
            r = subprocess.run([str(x) for x in common + ["--per-shot", PER_SHOT]], stdout=fh, stderr=subprocess.STDOUT)
            if r.returncode:
                raise RuntimeError(f"封面失败，见 {log}")


def song_title_zh(c, it):
    """歌名的中文译名：字幕片头那行的翻译（translate_ass 的 __title__ 缓存）；和原文一样（TQG / Dai Dai）就没有。"""
    cache = read_json(c.song_dir(it) / "zh_cache.json", {}) or {}
    zh = next((v for k, v in cache.items() if k.startswith("__title__::")), "")
    m = re.match(r"\s*《(.+?)》", zh or "")
    t = m.group(1).strip() if m else ""
    return "" if not t or t.lower() == it["title"].lower() else t


def post_title(c, it):
    """和 v1 同一个格式（make_meta.build_title）：演唱会名都不带歌手名（马德里演唱会2026 / Live from Madrid 2026）。"""
    import make_meta
    info = read_json(c.info)
    song = read_json(c.song_dir(it) / "song.json", {})
    langs = song.get("langs") or [song.get("lang", "en")]
    zh, en = info.get("artist_zh") or info["artist"], info["artist"]
    c_zh = (info.get("title_zh") or "").replace(zh, "", 1).strip()
    c_en = re.sub(rf"^{re.escape(en)}\s+", "", info.get("title") or "").strip()
    return make_meta.build_title(zh, en, it["title"], song_title_zh(c, it), c_zh, c_en,
                                 make_meta.subs_tag([LANG_ZH.get(x, "外语") for x in langs]))


def fit_title(title, limit=80):
    """B 站标题上限 80 字：从末尾一个个去掉搜索关键词（《歌名》和艺人名之前的部分不动）。"""
    head, sep, tail = title.partition("》")
    words = tail.split(" ")
    while len(head + sep + " ".join(words)) > limit and len(words) > 1:
        words.pop()
    return head + sep + " ".join(words)


def draft_meta(c, it, seg, a):
    d = c.song_dir(it)
    dst = d / "post_draft.json"
    if dst.exists() and not a.force:
        draft = read_json(dst)
        if draft.get("title") != post_title(c, it):   # 标题格式改过：只换标题，不重写介绍
            draft["title"] = post_title(c, it)
            write_json(dst, draft)
        return
    import make_meta
    from llm import chat_json
    info = read_json(c.info)
    song = read_json(d / "song.json", {})
    lang = "、".join(LANG_ZH.get(x, "原文") for x in (song.get("langs") or [song.get("lang", "en")]))
    songs = c.song_items()
    pos = next(i for i, x in enumerate(songs, 1) if x["name"] == it["name"])
    facts = {
        "演唱会": info.get("title"), "艺人": info.get("artist"), "巡演": info.get("tour"),
        "日期": info.get("date"), "场馆": info.get("venue"), "城市": info.get("city"),
        "本场第几首": f"{pos} / {len(songs)}", "歌名": it["title"],
        "原唱 / 合作": it.get("artist"), "歌单备注（setlist.fm）": it.get("notes") or "无",
        "片段时长（秒）": round(seg["end"] - seg["start"]),
        "转播": info.get("broadcast"),
        "Genius 歌曲信息（发行日期、原唱、合作艺人）": [x for x in song.get("genius", []) if x],
    }
    user = ("原视频信息（整场演唱会中的一首，以下是全部可用事实）：\n" + json.dumps(facts, ensure_ascii=False, indent=2)
            + f"\n\n字幕：{lang} + 中文（标签写作“中{''.join(x[0] for x in lang.split('、'))}字幕”）"
            + "\n\n补充说明：歌单备注里的英文请转述成中文，不要照抄。"
            + "\n\n介绍篇幅（覆盖上面的字数要求）：intro_song 和 intro_performance 各写 300~400 字，内容要充实："
            + "intro_song 写这首歌的创作 / 发行背景、原唱与合作、风格和主题、成绩与影响；"
            + "intro_performance 写这场演唱会（巡演、场馆、城市、转播）、这首歌在本场的位置和前后衔接、"
            + "歌单备注里的现场改编或嘉宾、适合观众留意的看点。只写材料里有的事实和广为人知的常识，不编数字和日期。")
    gen = {}
    for _ in range(2):   # 太短就再写一次
        gen = chat_json(make_meta.SYSTEM_PROMPT, user, temperature=0.5, label=f"元数据 {it['title']}")
        if min(len(gen.get("intro_song") or ""), len(gen.get("intro_performance") or "")) >= 220:
            break
    write_json(dst, {
        "title": post_title(c, it),
        "song": {"title": gen.get("song_title") or it["title"], "artist": gen.get("artist_en"),
                 "artist_zh": gen.get("artist_zh"), "release_year": gen.get("release_year")},
        "performance": {"event": gen.get("event") or info.get("title"), "date": gen.get("event_date") or info.get("date")},
        "intro": {"song": gen.get("intro_song"), "performance": gen.get("intro_performance")},
        "intro_text": "\n\n".join(x.strip() for x in (gen.get("intro_song"), gen.get("intro_performance")) if x),
        "tags": gen.get("tags", []),
        "subtitles": lang.split("、") + ["中文"],
    })


def package_one(c, it, seg, a):
    try:
        draft_meta(c, it, seg, a)
        make_covers(c, it, seg, a)
        n = len(cover_candidates(c.song_dir(it)))
        print(f"{it['idx']:>2} {it['title']}: 封面候选 {n} 张，介绍草稿 ✓", flush=True)
        return True
    except Exception as e:  # noqa: BLE001 一首失败不影响其他
        print(f"{it['idx']:>2} {it['title']}: ✗ {e}", flush=True)
        return False


def stage_package(c, a):
    todo = selected(c, a)
    # 介绍只调接口，可以 3 首并发；封面要跑 Real-ESRGAN（本地重模型），一次只跑一首
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda x: draft_meta(c, *x, a), todo))
    res = [package_one(c, *x, a) for x in todo]
    print(f"\npackage：{sum(res)}/{len(todo)} 首完成")
