# -*- coding: utf-8 -*-
"""
整场封面池：封面不限于这首歌自己那几分钟，整场演唱会里好看的画面都能给任何一首歌用。

    .venv/bin/python -m workflow.live.cover_pool lorde_lolla_chile2026           # 1) 生成封面池
    .venv/bin/python -m workflow.live.cover_pool lorde_lolla_chile2026 filter    #    现有的帧按硬条件重新筛
    .venv/bin/python -m workflow.live.cover_pool lorde_lolla_chile2026 assign    # 3) 标记的画面随机分给要做的歌

  1) 整场切成 POOL_WINDOWS 段、每段各挑一批（make_cover.py：正脸特写 / 半身，只留高清原始帧、不排字；舞台全景、大屏幕做不了封面，不挑），
     Qwen 先判硬条件（本人不是大屏、看得清正脸、是画面主体、不太暗），不过的删掉，过了的打分，
     任意 60 秒里最多 PER_MINUTE 张、每首最多 PER_SONG 张（同一个镜头只留分高的），留 POOL_KEEP 张，
     存到 concerts/<场次>/cover_pool/frame_<类>_<nn>_<整场秒>s.jpg；台标修补、去黑边等和每首的候选封面一样（看 concert.json）
  2) 用户在审核页「封面池」页面标记适合做封面的画面（cover_pool/marked.json）
  3) assign：出了字幕的歌（要做投稿的），从标记的画面里随机各分一张（标记的比歌少才重复用），
     按这首的歌名 / 副标题排出 16:9 + 4:3（covers/pool_<nn>.jpg、pool_<nn>_4x3.jpg），存成这首的封面（post/ 里的 PNG，
     和审核页「下载」一样），审核页这首的已选封面也设成它；分配结果记在 cover_pool/assigned.json
"""

import json
import random
import re
import shutil
import subprocess
import time
import sys
from pathlib import Path

from PIL import Image

from . import review
from .package import CLOSEUP_MIN, TEXT_LIFT, save_picked, subtitle_line
from .paths import ROOT, VENV_PY, Concert, read_json, write_json

POOL_WINDOWS = 10                           # 整场切成 10 段，每段各挑一批（只在整场挑「最好的」会全挤在一两段里）
POOL_SHOTS = "closeup=8,half=6,full=0"      # 每段：特写 8、半身 6（舞台全景、大屏幕做不了封面，不挑）
POOL_KEEP = 60                              # 过了硬条件、打分 + 去重之后最多留这么多给用户标记
PER_SONG = 4                                # 同一首歌（或两首之间）最多留几张（画面分散到整场）
PER_MINUTE = 2                              # 任意 60 秒里最多留 2 张（同一个镜头的画面时间挨着，画面指纹去不掉）
MIN_SCORE = 6                               # 过了硬条件还要 6 分以上
FRAME_RE = re.compile(r"^frame_(closeup|half|full|scene)_(\d\d)_([\d.]+)s\.jpg$")
SCORE_SYSTEM = "你是演唱会视频的封面编辑，负责从演唱会截图里挑能做视频封面的画面。"
# 舞台全景、拍大屏幕、背影都做不了封面（用户 2026-10-24：「屏幕后面的」「氛围和舞台看不出来任何东西」），先过硬条件再打分
SCORE_PROMPT = ("下面 {n} 张截图（图1、图2……）来自同一场演唱会。先判断每张能不能做 B 站视频封面，四条都满足才算能（usable=true）：\n"
                "1. 拍的是歌手本人，不是舞台大屏幕 / 背景屏上的她\n"
                "2. 能看清歌手的正脸或大半张脸（不是背影、后脑勺、侧后方）\n"
                "3. 歌手是画面主体、在画面里够大（至少是半身，不是远景全景里的小人）\n"
                "4. 不太暗、不模糊\n"
                "再给能用的打 0~10 分：表情有感染力、脸不被话筒挡、光线和构图好看的高分。不能用的 score 给 0。\n"
                '输出 JSON：{{"items": [{{"id": "图1", "usable": true, "score": 8, "why": "一句话"}}]}}')
def pool_dir(c):
    return c.dir / "cover_pool"


def score_frames(files):
    """Qwen 给每帧打「适合做封面」的分：{文件名: (分, 理由)}，每批 16 张。"""
    import io
    sys.path.insert(0, str(ROOT / "workflow"))
    from llm import vision_json
    out = {}
    for k in range(0, len(files), 16):
        batch = files[k:k + 16]
        payload = []
        for i, f in enumerate(batch, 1):
            b = io.BytesIO()
            Image.open(f).convert("RGB").resize((640, 360)).save(b, "JPEG", quality=85)
            payload.append((f"图{i}", b.getvalue()))
        try:
            r = vision_json(SCORE_SYSTEM, SCORE_PROMPT.format(n=len(batch)), payload, label=f"封面池打分 {k // 16 + 1}")
        except Exception as e:  # noqa: BLE001
            print(f"  这一批打分失败（{e}），按 0 分算")
            continue
        for x in r.get("items") or []:
            i = str(x.get("id", "")).replace("图", "").strip()
            if i.isdigit() and 1 <= int(i) <= len(batch):
                ok = x.get("usable") is True
                out[batch[int(i) - 1].name] = (float(x.get("score") or 0) if ok else 0.0, ("" if ok else "不能做封面：") + (x.get("why") or ""))
    return out


def build(slug):
    c = Concert(slug)
    info = read_json(c.info)
    out = pool_dir(c)
    out.mkdir(exist_ok=True)
    common = [VENV_PY, ROOT / "workflow" / "make_cover.py", "--name", f"{slug}_pool", "--title", "Pool",
              "--video", c.source, "--closeup-min", CLOSEUP_MIN]
    if info.get("cover_inpaint_static"):
        common += ["--inpaint-static"]
    if info.get("cover_inpaint_corners"):
        common += ["--inpaint-corners"]
    log = c.dir / "logs" / "cover_pool.log"
    dur = float(info.get("duration") or 0)
    with log.open("a") as fh:
        for k in range(POOL_WINDOWS):
            a, b = dur * k / POOL_WINDOWS, dur * (k + 1) / POOL_WINDOWS
            # 每段写进自己的临时目录：make_cover 每跑一次会清掉输出目录里同类的旧图，都写进 out 就只剩最后一段
            wdir = out / f"_window_{k:02d}"
            r = subprocess.run([str(x) for x in common + ["--out-dir", wdir, "--per-shot", POOL_SHOTS,
                                                          "--start", f"{a:.1f}", "--end", f"{b:.1f}"]],
                               stdout=fh, stderr=subprocess.STDOUT)
            n = 0
            for f in wdir.glob("frame_*.jpg"):   # 文件名带整场时间，不会重名
                f.rename(out / f.name)
                n += 1
            shutil.rmtree(wdir, ignore_errors=True)
            print(f"  第 {k + 1}/{POOL_WINDOWS} 段 {a / 60:.0f}–{b / 60:.0f} 分钟：{n} 帧"
                  + ("" if r.returncode == 0 else f" ✗ 见 {log}"), flush=True)
    # 排了占位标题的封面没用，只留原始帧
    for f in out.iterdir():
        if f.suffix == ".jpg" and not f.name.startswith("frame_"):
            f.unlink()
    refilter(slug)


def refilter(slug):
    """封面池里现有的帧重新过一遍：Qwen 判硬条件 + 打分，不能用 / 分低的、同一个镜头的、某首歌太多的删掉（标记过的留着）。"""
    c = Concert(slug)
    out = pool_dir(c)
    marked = marks(c)
    files = [out / x["file"] for x in frames(c)]
    scores = score_frames(files)
    song_of = {x["file"]: x["song"] for x in frames(c)}
    time_of = {x["file"]: x["t"] for x in frames(c)}
    keep, per = [], {}
    for f in sorted(files, key=lambda f: (f.name not in marked, -scores.get(f.name, (0, ""))[0])):
        if f.name not in marked:
            if f.name.startswith("frame_scene_") or scores.get(f.name, (0, ""))[0] < MIN_SCORE:   # 舞台全景一律不要
                continue
            t = time_of[f.name]
            if sum(1 for k in keep if abs(time_of[k.name] - t) < 60) >= PER_MINUTE:
                continue
            s = song_of.get(f.name)
            if per.get(s, 0) >= PER_SONG:
                continue
            if len(keep) >= POOL_KEEP:
                continue
        s = song_of.get(f.name)
        keep.append(f)
        per[s] = per.get(s, 0) + 1
    for f in files:
        if f not in keep:
            f.unlink()
    write_json(out / "scores.json", {f.name: {"score": scores.get(f.name, (0, ""))[0], "why": scores.get(f.name, (0, ""))[1]}
                                     for f in keep})
    print(f"{slug}：{len(files)} 帧过硬条件 + 打分 + 去重，留 {len(keep)} 帧（标记的 {len(marked & {f.name for f in keep})} 张照留）")


def marks(c):
    return set(read_json(pool_dir(c) / "marked.json", []) or [])


def set_mark(c, file, on):
    m = marks(c)
    if not FRAME_RE.match(file) or not (pool_dir(c) / file).is_file():
        raise ValueError("封面池里没有这一帧")
    (m.add if on else m.discard)(file)
    write_json(pool_dir(c) / "marked.json", sorted(m))
    return len(m)


def targets(c):
    """要分封面的歌：出了字幕的（这次要做投稿的）。"""
    return [it for it in c.song_items() if (c.song_dir(it) / "subs" / "lyrics_poetic.ass").exists()]


def assign(slug, seed=None):
    c = Concert(slug)
    picked = sorted(marks(c))
    songs = targets(c)
    if not picked:
        raise ValueError("还没有标记的画面：先在审核页「封面池」里标记")
    rnd = random.Random(seed)
    order = picked[:]
    rnd.shuffle(order)
    out = {}
    for i, it in enumerate(songs):
        f = order[i % len(order)]   # 标记的比歌少：轮着重复用
        cid = compose_for(slug, it["name"], f)
        save_picked(c, it, cid)
        review.save_entry(c, it, {"cover": cid})
        out[it["name"]] = {"frame": f, "cover": cid}
        print(f"{it['title']} <- {f}（{cid}）")
    write_json(pool_dir(c) / "assigned.json", {"at": time.strftime("%Y-%m-%d %H:%M"), "songs": out})
    return out


def frames(c):
    """封面池里的帧：[{file, kind, t, song, marked}]，t 是整场时间，song 是这一刻在哪首歌里（不在任何一首里是 None）。"""
    marked = marks(c)
    scores = read_json(pool_dir(c) / "scores.json", {}) or {}
    segs = [(s["name"], s.get("start"), s.get("end")) for s in (c.load("segments") or {}).get("items", [])]
    out = []
    for f in sorted(pool_dir(c).glob("frame_*.jpg")) if pool_dir(c).exists() else []:
        m = FRAME_RE.match(f.name)
        if not m:
            continue
        t = float(m[3])
        song = next((n for n, a, b in segs if a is not None and b is not None and a <= t < b), None)
        sc = scores.get(f.name) or {}
        out.append({"file": f.name, "kind": m[1], "t": t, "song": song, "marked": f.name in marked,
                    "score": sc.get("score"), "why": sc.get("why", "")})
    return sorted(out, key=lambda x: (-(x["score"] or 0), x["t"]))   # 分高的在前


def compose_for(slug, name, file):
    """池里的一帧按这首歌的歌名 / 副标题排版，存进这首的 covers/ 当候选；返回候选 id（pool_<nn>）。
    同一帧给同一首歌排过就直接返回原来的 id。"""
    sys.path.insert(0, str(ROOT / "workflow"))
    import make_cover
    c = Concert(slug)
    it = c.item(name)
    m = FRAME_RE.match(file)
    src = pool_dir(c) / file
    if not m or not src.is_file():
        raise ValueError("封面池里没有这一帧")
    cdir = c.song_dir(it) / "covers"
    cdir.mkdir(exist_ok=True)
    t = m[3]
    for f in cdir.glob("frame_pool_*_*s.jpg"):
        if f.name.endswith(f"_{t}s.jpg"):
            return "pool_" + f.name.split("_")[2]
    n = 1 + max([int(f.name.split("_")[2]) for f in cdir.glob("frame_pool_*.jpg")] or [0])
    cid = f"pool_{n:02d}"
    img = Image.open(src).convert("RGB")
    c169, c43 = make_cover.compose_pair(img, ["--name", it["name"], "--title", it["title"], "--subtitle", subtitle_line(c, it),
                                              "--sub-fit", "natural", "--text-lift", TEXT_LIFT])
    c169.convert("RGB").save(cdir / f"{cid}.jpg", quality=95)
    c43.convert("RGB").save(cdir / f"{cid}_4x3.jpg", quality=95)
    img.save(cdir / f"frame_{cid}_{t}s.jpg", quality=95)
    return cid


if __name__ == "__main__":
    if sys.argv[2:3] == ["assign"]:
        assign(sys.argv[1])
    elif sys.argv[2:3] == ["filter"]:
        refilter(sys.argv[1])
    else:
        build(sys.argv[1])
