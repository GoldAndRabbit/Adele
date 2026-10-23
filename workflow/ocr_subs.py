# -*- coding: utf-8 -*-
"""
从烧在画面里的双语字幕把歌词认出来（OCR），用 macOS 自带的 Vision 文字识别（本地、免费，pyobjc-framework-Vision）。
用途：自己以前发过的成品视频只剩视频、没留歌词和翻译时，把「原文 + 中文」两行字幕抄回来。

    .venv/bin/python workflow/ocr_subs.py VIDEO --out posts/X/reports/ocr [--ref genius_lyrics.txt] [--fps 3] [--band 0.62,0.88]

做法：
  1) 每秒抽 fps 帧，只看字幕那一条带（band：画面高度的比例，默认 62%～88%，bzrp 样式的双语字幕在这里）
  2) 中文行两头的 ♪ 会被认成「J / 了 / 小 / 』」之类，又不能按字删（有的句子本来就以「上」「化」开头）：
     先在开头几帧里找一个 ♪ 截成模板，之后每帧把和模板匹配的地方涂黑再识别
  3) 只要水平居中的文字行（画面里的球衣、横幅一般不居中）；从上到下，含汉字的行算中文、其余算原文；全角标点换半角
  4) 连续的帧文字差不多（相似度 ≥ 80）算同一句，这句取各帧里出现最多的写法（个别帧认错的被投票刷掉）；
     同一句因为个别帧认错被拆成两段的（文字一样、中间没有空白帧）合并；中间有空白帧的是重复唱的两句，不合并；
     片头歌名卡（《…》）和零碎的一两个字去掉
  5) 给了 --ref（比如 Genius 原文）时：在参考里找和这句最像的一段词，逐词对齐，只把不是正常单词的（OCR 认错的）
     换成参考里对应的词；大小写、标点、措辞都照视频（视频和参考的措辞可能不同，以视频为准）
产物（--out 目录）：
    ocr.json        [{start, end, orig, zh, ocr}]（秒；ocr = 校正前认出来的原文）
    lyrics.txt      原文，一句一行（当参考歌词用）
    lyrics_zh.txt   「原文 \\t 中文」，一句一行
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz

CJK = re.compile(r"[㐀-鿿]")
NOTE_LIKE = set("♪♫『』「」J")   # ♪ 常被认成的字符（找模板用）
FULL = str.maketrans("！？，．：；（）“”‘’", "!?,.:;()\"\"''")
# Genius 歌词里夹着长得一样的西里尔字母（防抓取），比较和输出前换回拉丁字母
HOMO = str.maketrans("аеорсухіјѕԁАВЕКМНОРСТХІЈЅ", "aeopcyxijsdABEKMHOPCTXIJS")


def vision(path, langs=("zh-Hans", "en-US", "es-ES")):
    """一张图里的文字行：[(文字, 框 (x0, y0, x1, y1)，0~1、原点左上)]。"""
    import Quartz
    import Vision
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(list(langs))
    req.setUsesLanguageCorrection_(False)   # 歌词不是规范句子，别让它「纠正」
    Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None).performRequests_error_([req], None)
    out = []
    for ob in req.results() or []:
        cand = ob.topCandidates_(1)
        if cand:
            b = ob.boundingBox()   # Vision 的坐标原点在左下
            out.append((str(cand[0].string()), (b.origin.x, 1 - b.origin.y - b.size.height, b.origin.x + b.size.width, 1 - b.origin.y)))
    return sorted(out, key=lambda x: x[1][1])


def find_note_template(frames):
    """在前面的帧里找一行「♪ 中文 ♪」：两头都是 ♪ 常被认成的字符，就把第一个字的位置截下来当 ♪ 模板。"""
    import cv2
    for f in frames[::3][:200]:
        for s, (x0, y0, x1, y1) in vision(f):
            if CJK.search(s) and len(s) >= 4 and s[0] in NOTE_LIKE and s[-1] in NOTE_LIKE:
                im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
                H, W = im.shape
                cw = (x1 - x0) * W / len(s)
                return im[int(y0 * H):int(y1 * H), int(x0 * W):int(x0 * W + cw)]
    return None


def mask_notes(path, tpl, thr=0.5):
    """把和 ♪ 模板匹配的地方涂黑（原地改图）。"""
    import cv2
    import numpy as np
    im = cv2.imread(str(path))
    r = cv2.matchTemplate(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), tpl, cv2.TM_CCOEFF_NORMED)
    h, w = tpl.shape
    for y, x in zip(*np.where(r > thr)):
        cv2.rectangle(im, (int(x), int(y)), (int(x) + w, int(y) + h), (0, 0, 0), -1)
    cv2.imwrite(str(path), im)


def clean(t, zh):
    t = re.sub(r"[♪♫『』「」]", " ", t)
    t = re.sub(r"^[\s\-–—~•]+|[\s\-–—~•]+$", "", t)
    if not zh:
        t = t.translate(FULL)
    return re.sub(r"\s+", " ", t).strip()


def frame_text(path):
    orig, zh = [], []
    for t, (x0, _, x1, _) in vision(path):
        if abs((x0 + x1) / 2 - 0.5) > 0.12:   # 字幕是居中的
            continue
        is_zh = bool(CJK.search(t))
        t = clean(t, is_zh)
        if t:
            (zh if is_zh else orig).append(t)
    return " ".join(orig), " ".join(zh)


def norm(t):
    return re.sub(r"[^\w' ]+", "", t.translate(HOMO).lower()).strip()


def sim(a, b):
    return fuzz.ratio(norm(a), norm(b))


def segments(reads, step):
    """reads = [(t, orig, zh)] → 一句一段，每段各帧投票。"""
    blank = [t for t, o, z in reads if not o and not z]   # 没有字幕的帧：两句之间真正的空档
    groups = []
    for t, o, z in reads:
        g = groups[-1] if groups else None
        if g and t - g["frames"][-1][0] <= step * 1.5 and (sim(o, g["frames"][-1][1]) >= 80 or sim(z, g["frames"][-1][2]) >= 80):
            g["frames"].append((t, o, z))
        elif o or z:
            groups.append({"frames": [(t, o, z)]})
    vote = lambda xs: max(Counter(x for x in xs if x).items(), key=lambda kv: (kv[1], len(kv[0])), default=("", 0))[0]
    segs = [{"start": g["frames"][0][0], "end": g["frames"][-1][0] + step,
             "orig": vote([f[1] for f in g["frames"]]), "zh": vote([f[2] for f in g["frames"]])} for g in groups]
    merged = []
    for s in segs:   # 被一帧没认出来拆开的同一句
        p = merged[-1] if merged else None
        if (p and s["start"] - p["end"] <= 0.7 and sim(s["orig"], p["orig"]) >= 85 and sim(s["zh"], p["zh"]) >= 85
                and not any(p["end"] - step <= t < s["start"] for t in blank)):
            p["end"] = s["end"]
        else:
            merged.append(dict(s))
    keep = lambda s: (s["end"] - s["start"] >= 0.6 and not s["orig"].startswith("《")
                      and (len(s["orig"]) > 3 or len(s["zh"]) > 2))
    return [{**s, "start": round(s["start"], 2), "end": round(s["end"], 2)} for s in merged if keep(s)]


def snap(segs, ref_lines, thr=80):
    """原文按参考歌词修 OCR 认错的词：在参考里找和这句最像的一段连续的词（≥ thr），逐词对齐，
    只把「不是正常单词」的词（认错的 stadfums、Iiquor、粘在一起的 Aslwalk、竖线 |）换成参考里对应的词；
    大小写、标点、措辞（视频里是 a London、参考是 the London；有意打码的 f**kers）都照视频。"""
    import difflib
    refs = [r.translate(HOMO).split() for r in ref_lines]
    key = lambda w: re.sub(r"[^\w]", "", w.translate(HOMO).lower())
    words_ok = english_words() | {key(w) for r in refs for w in r}   # 参考里出现过的俚语、地名也算正常单词
    for s in segs:
        s["ocr"] = s["orig"]
        toks = s["orig"].split()
        if not toks or not refs:
            continue
        n = len(toks)
        cands = [(sim(s["orig"], " ".join(words[i:i + k])), words[i:i + k]) for words in refs for k in range(max(1, n - 2), n + 3)
                 for i in range(0, max(1, len(words) - k + 1))]
        top = max(sc for sc, _ in cands)
        if top < thr:
            continue
        ref = min((c for sc, c in cands if sc >= top - 3), key=lambda c: (abs(len(norm("".join(c))) - len(norm(s["orig"]).replace(" ", ""))), -len(c)))   # 一样接近时取词多的（别丢开头）
        bad = lambda w: "*" not in w and (not re.fullmatch(r"[\w'’.,!?\"-]+", w) or key(w).replace("'", "") not in words_ok)
        out, blocks = [], []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [key(w) for w in toks], [key(w) for w in ref]).get_opcodes():
            if op != "equal" and blocks and blocks[-1][0] != "equal":   # 连着的几处差异并成一段（Aslwalk ↔ As I walk）
                blocks[-1] = ("diff", blocks[-1][1], i2, blocks[-1][3], j2)
            else:
                blocks.append(("equal" if op == "equal" else "diff", i1, i2, j1, j2))
        for op, i1, i2, j1, j2 in blocks:
            if op == "equal" or not any(bad(w) for w in toks[i1:i2]):
                out += toks[i1:i2]
            else:   # 有认错的词：这一段换成参考的词（去掉参考的标点；只有句首大写）
                rep = [re.sub(r"[,.;:]+$", "", w) for w in ref[j1:j2]]
                rep = [w[0].upper() + w[1:] if k == 0 and i1 == 0 else (w.lower() if len(w) > 1 and w[:1].isupper() and w.lower() in words_ok else w)
                       for k, w in enumerate(rep)]
                out += rep
        s["orig"] = " ".join(out)
    return segs


def english_words():
    """macOS 自带的英文词表（/usr/share/dict/words）。"""
    f = Path("/usr/share/dict/words")
    return {w.strip().lower() for w in f.read_text().splitlines()} if f.exists() else set()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--out", required=True)
    p.add_argument("--ref", help="参考歌词（一句一行，比如 Genius 原文），用来校正 OCR 拼写")
    p.add_argument("--fps", type=float, default=3)
    p.add_argument("--band", default="0.62,0.88", help="字幕区：画面高度的比例 上,下")
    a = p.parse_args()
    b0, b1 = (float(x) for x in a.band.split(","))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ocr_"))
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-i", a.video, "-vf",
                        f"fps={a.fps},crop=iw:ih*{b1 - b0}:0:ih*{b0},scale=1920:-2",
                        str(tmp / "%06d.png")], check=True)
        frames = sorted(tmp.glob("*.png"))
        tpl = find_note_template(frames)
        print("♪ 模板：" + ("找到了，识别前先涂掉" if tpl is not None else "没找到（字幕可能没有 ♪），直接识别"), flush=True)
        reads = []
        for i, f in enumerate(frames):
            if tpl is not None:
                mask_notes(f, tpl)
            reads.append((i / a.fps, *frame_text(f)))
            if i % 150 == 0:
                print(f"{i}/{len(frames)} 帧", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ref = [x.strip() for x in Path(a.ref).read_text().splitlines() if x.strip() and not x.startswith("[")] if a.ref else []
    segs = snap(segments(reads, 1 / a.fps), ref)
    (out / "ocr.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1) + "\n")
    (out / "lyrics.txt").write_text("\n".join(s["orig"] for s in segs if s["orig"]) + "\n")
    (out / "lyrics_zh.txt").write_text("\n".join(f"{s['orig']}\t{s['zh']}" for s in segs) + "\n")
    fixed = sum(1 for s in segs if s.get("ocr") != s["orig"])
    print(f"{len(segs)} 句（按参考校正拼写 {fixed} 句）→ {out}")


if __name__ == "__main__":
    main()
