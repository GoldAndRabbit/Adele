# -*- coding: utf-8 -*-
"""
segment：定位每首歌在整场里的起止 -> segments.json。

1) 粗定位（文本）：内嵌字幕轨（直播实时字幕，滚动显示）还原成连续词流，每 3 个词取一个 10 词窗口，
   和歌单里每首歌的歌词逐行模糊匹配；按歌单顺序做单调 DP（每首歌一段连续窗口，中间允许讲话/过场），
   得到每首歌第一句、最后一句大致在哪。没有字幕轨时用 Qwen ASR 识别人声代替（_asr_words）。
2) 精修：
   - 转播画面上有歌名字幕（concert.json 的 title_box 给出位置，如 Amazon 转播左下角）：整场每个关键帧 OCR，
     歌名出现的时段就是这首歌（含前奏尾奏），最可靠
   - 否则用音频：从第一句往前找前奏起点、从最后一句往后找尾奏 + 掌声（准确度有限，审核页人工调）
   - 两种情况都把歌前紧挨着的讲话（人声活跃但不在奏乐，≤ 60s）并进这首
3) 人工在审核页上改过的边界（manual=true）重跑时保留，--force 才覆盖。
"""

import re
import unicodedata

import numpy as np

from .paths import read_json, write_json
from .util import hms

WIN, STEP = 10, 3            # 字幕词窗口：10 个词，步长 3
MIN_LINE = 12                # 参与匹配的歌词行至少这么多字符（太短的行到处都能匹配上）
HIT, MARGIN = 85, 6          # 窗口匹配度 >= HIT、且比其他歌高 MARGIN，才算这首歌的证据
CLUSTER_GAP = 90.0           # 证据之间隔超过这么久就分簇，取证据最多的一簇（防止零星误匹配把一首歌拉长）
CAPTION_LAG = 2.5            # 实时字幕比开口晚的秒数（经验值）
WIN_SPAN = 3.5               # 一个 10 词窗口大约覆盖的演唱时长
HOP = 0.1                    # 音频特征帧长
MAX_INTRO, MAX_OUTRO = 50.0, 40.0
MAX_TALK = 60.0              # 歌前不超过这么长的讲话并进这首歌
APPLAUSE_TAIL = 3.0
SEP_GAP = 75.0               # 歌名首帧离前一个分隔帧这么近，中间算这首的前奏


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", s)).strip()


# ---------------------------------------------------------------- 文本：字幕词流 + 匹配 + DP

def caption_words(path):
    """滚动字幕每条事件显示最近一两行；和上一条重叠的前缀去掉，只留新出现的词，时间取事件开始。"""
    import pysubs2
    words, prev = [], []
    for e in pysubs2.load(str(path)).events:
        cur = norm(e.plaintext.replace("\n", " ")).split()
        k = next((n for n in range(min(len(prev), len(cur)), 0, -1) if prev[-n:] == cur[:n]), 0)
        words += [(e.start / 1000, w) for w in cur[k:]]
        if cur:
            prev = cur
    return words


def windows(words):
    return [(words[i][0], words[min(i + WIN, len(words)) - 1][0], " ".join(w for _, w in words[i:i + WIN]))
            for i in range(0, max(1, len(words) - WIN), STEP)]


def score_matrix(wins, songs, lyrics):
    """S[i, k] = 第 i 个窗口和第 k 首歌任一行歌词的最大 partial_ratio。"""
    from rapidfuzz import fuzz, process
    lines, owner = [], []
    for k, it in enumerate(songs):
        for l in lyrics[it["name"]]:
            l = norm(l)
            if len(l) >= MIN_LINE:
                lines.append(l)
                owner.append(k)
    owner = np.array(owner)
    M = process.cdist([w for *_, w in wins], lines, scorer=fuzz.partial_ratio, workers=-1, dtype=np.uint8)
    S = np.zeros((len(wins), len(songs)), np.float32)
    for k in range(len(songs)):
        if (owner == k).any():
            S[:, k] = M[:, owner == k].max(1)
    return S


def specific(S):
    """窗口只像这一首（比其他歌高出 MARGIN）才算这首的证据；oh oh / baby 这类到处都能匹配上的不算。"""
    other = np.zeros_like(S)
    for k in range(S.shape[1]):
        other[:, k] = np.delete(S, k, axis=1).max(1) if S.shape[1] > 1 else 0
    return (S >= HIT) & (S - other >= MARGIN)


def order_dp(S, skip_pen=150.0):
    """状态 2k = 第 k 首之前的空档，2k+1 = 第 k 首；只能往后走（按歌单顺序）。
    窗口放进第 k 首：只像这首的得 (S - HIT + 4)，明显不是这首（S < 70）扣 6，其余 0；放进空档 0 分。
    允许跳过一首（罚 skip_pen），例如歌单写了但这场转播里没有。返回每个窗口的状态。"""
    N, K = S.shape
    ns = 2 * K + 1
    spec = specific(S)
    emit = np.zeros((N, ns), np.float32)
    for k in range(K):
        emit[:, 2 * k + 1] = np.where(spec[:, k], S[:, k] - HIT + 4, np.where(S[:, k] < 70, -6.0, 0.0))
    NEG = -1e18
    dp = np.full(ns, NEG)
    dp[0], dp[1] = emit[0, 0], emit[0, 1]
    back = np.zeros((N, ns), np.int16)
    for i in range(1, N):
        new = np.full(ns, NEG)
        for s in range(ns):
            # 来源：s（停留）、s-1（前进一格）、s-2（两首歌直接衔接，跳过空档）、更远（跳过整首歌，罚分）
            best, arg = dp[s], s
            for d in (1, 2):
                if s - d >= 0 and dp[s - d] > best:
                    best, arg = dp[s - d], s - d
            for d in range(3, 7):
                if s - d >= 0 and dp[s - d] - skip_pen * (d // 2) > best:
                    best, arg = dp[s - d] - skip_pen * (d // 2), s - d
            new[s] = best + emit[i, s]
            back[i, s] = arg
        dp = new
    s = int(np.argmax(dp))
    path = np.zeros(N, np.int16)
    for i in range(N - 1, -1, -1):
        path[i] = s
        s = back[i, s]
    return path


def coarse_spans(c, songs, lyrics):
    """每首歌：字幕证据给出的 (第一句开口, 最后一句结束, 强匹配窗口数)。"""
    words = caption_words(c.captions) if c.captions.exists() else _asr_words(c)
    wins = windows(words)
    S = score_matrix(wins, songs, lyrics)
    path = order_dp(S)
    T0 = np.array([w[0] for w in wins])
    T1 = np.minimum(np.array([w[1] for w in wins]), T0 + 6.0)  # 字幕稀疏时一个窗口会跨过很长的空白
    spec = specific(S)
    spans, talk = [], []
    for k in range(len(songs)):
        idx = np.where((path == 2 * k + 1) & spec[:, k])[0]
        if len(idx) == 0:
            spans.append(None)
            continue
        clusters = np.split(idx, np.where(np.diff(T0[idx]) > CLUSTER_GAP)[0] + 1)
        best = max(clusters, key=len)
        spans.append({"first": float(T0[best[0]] - CAPTION_LAG), "last": float(T1[best[-1]] - CAPTION_LAG + 1.0),
                      "hits": int(len(best))})
    # 空档里的字幕词 = 讲话（或过场里的台词），审核页时间轴上显示，也用来判断歌前讲话
    gap = np.where(path % 2 == 0)[0]
    for i in gap:
        if not talk or T0[i] - talk[-1][1] > 4.0:
            talk.append([float(T0[i]), float(T1[i])])
        else:
            talk[-1][1] = float(T1[i])
    return spans, [(s - CAPTION_LAG, e - CAPTION_LAG + 1.0) for s, e in talk if e - s >= 2.0]


def _asr_words(c):
    """没有字幕轨：人声按 30s 窗口（重叠 5s）跑 Qwen ASR，按字数均分时间，当作字幕词流。"""
    import librosa
    from openai import OpenAI
    import llm
    from qwen_asr import ENDPOINT, SR, transcribe
    import os
    from concurrent.futures import ThreadPoolExecutor
    cache = c.dir / "asr_words.json"
    if cache.exists():
        return [tuple(x) for x in read_json(cache)]
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(str(c.vocals), sr=SR, mono=True)
    starts = np.arange(0, len(y) / SR, 25.0)

    def one(t):
        return t, transcribe(client, y[int(t * SR): int((t + 30) * SR)], None) or ""
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, starts))
    words = []
    for t, text in res:
        ws = norm(text).split()
        words += [(float(t + 30 * j / max(1, len(ws))), w) for j, w in enumerate(ws)]
    words.sort()
    write_json(cache, words)
    return words


# ---------------------------------------------------------------- 画面：歌名字幕 OCR

def title_ocr(c):
    """整场关键帧（约 1s 一个，只解码关键帧很快）裁出歌名字幕区域，阈值成黑字白底后 tesseract 识别。
    返回 [(秒, 文字)]，缓存 title_ocr.json。concert.json 没有 title_box 就返回 []。"""
    import re as _re
    import shutil
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    box = read_json(c.info).get("title_box")
    if not box:
        return []
    cache = c.dir / "title_ocr.json"
    if cache.exists():
        return [tuple(x) for x in read_json(cache)]
    if not shutil.which("tesseract"):
        print("⚠ 没有 tesseract（brew install tesseract），不用歌名字幕")
        return []
    tmp = c.dir / "_title_ocr"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    x, y, w, h = box
    print("整场关键帧歌名 OCR（一次）...", flush=True)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-skip_frame", "nokey", "-i", str(c.source), "-an",
                        "-vf", f"crop={w}:{h}:{x}:{y},format=gray,lut=y='if(gt(val,200),0,255)',scale=iw*2:-1,showinfo",
                        "-fps_mode", "passthrough", str(tmp / "%06d.png")], capture_output=True, text=True)
    times = [float(m) for m in _re.findall(r"pts_time:([\d.]+)", r.stderr)]
    files = sorted(tmp.glob("*.png"))

    def ocr(f):
        out = subprocess.run(["tesseract", str(f), "-", "--psm", "7"], capture_output=True, text=True).stdout
        return " ".join(out.split())
    with ThreadPoolExecutor(8) as ex:
        texts = list(ex.map(ocr, files))
    res = [(t, tx) for t, tx in zip(times, texts) if len(norm(tx)) >= 3]
    write_json(cache, res)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  {len(files)} 帧，{len(res)} 帧有文字")
    return res


def title_match(tx, names):
    """OCR 文字是不是这首歌的歌名。只允许 OCR 文字比歌名长时做部分匹配（MADRID 不能算 TE DEJO MADRID）。"""
    from rapidfuzz import fuzz
    t = norm(tx).replace(" ", "")
    for n in names:
        n = n.replace(" ", "")  # OCR 常把空格吃掉：LABICICLETA
        if len(n) < 3:
            continue
        if fuzz.ratio(t, n) >= 80 or (len(t) >= len(n) >= 6 and fuzz.partial_ratio(n, t) >= 90):
            return True
        # 转播只写歌名前半截：PIES DESCALZOS = Pies descalzos, sueños blancos
        if len(t) >= 8 and len(n) > len(t) and fuzz.ratio(t, n[:len(t)]) >= 90:
            return True
    return False


def title_spans(ocr, songs, coarse, gap=20.0):
    """每首歌：OCR 文字对得上歌名（或串烧里任一首）的关键帧，按间隔分簇，取和字幕粗区间重叠最多的一簇。
    另外记下前后最近的「分隔帧」（别的文字，如歌间显示的 MADRID、别的歌名）：这首歌的边界不能越过它们。"""
    names = []
    for it in songs:
        ns = [norm(x) for x in [it["title"], *it.get("parts", [])]]
        # 括号里的副标题转播上不一定写（Suerte (Whenever, Wherever) 只显示 SUERTE）
        ns += [norm(re.sub(r"\s*\([^)]*\)", "", x)) for x in [it["title"], *it.get("parts", [])]]
        names.append(set(ns))
    owner = [next((k for k, ns in enumerate(names) if title_match(tx, ns)), None) for _, tx in ocr]
    out = []
    for k, sp in enumerate(coarse):
        ts = sorted(t for (t, _), o in zip(ocr, owner) if o == k)
        if not ts or sp is None:
            out.append(None)
            continue
        clusters, cur = [], [ts[0]]
        for t in ts[1:]:
            if t - cur[-1] > gap:
                clusters.append(cur)
                cur = []
            cur.append(t)
        clusters.append(cur)

        def overlap(cl):
            return max(0.0, min(cl[-1], sp["last"]) - max(cl[0], sp["first"]))
        best = max(clusters, key=lambda cl: (overlap(cl), len(cl)))
        if overlap(best) <= 0 and not (best[0] - 120 < sp["first"] < best[-1] + 120):
            out.append(None)
            continue
        # 同一首歌字幕中途被别的画面盖住一会儿：把挨着的簇（间隔 < 60s）也并进来
        i = clusters.index(best)
        lo, hi = best[0], best[-1]
        for cl in reversed(clusters[:i]):
            if lo - cl[-1] < 60:
                lo = cl[0]
            else:
                break
        for cl in clusters[i + 1:]:
            if cl[0] - hi < 60:
                hi = cl[-1]
            else:
                break
        # 分隔帧：连续 3 帧以上不是这首歌的文字（单帧 OCR 噪声不算）
        others = [t for (t, tx), o in zip(ocr, owner) if o != k and len(norm(tx)) >= 4]
        def solid(ts_, t):
            return sum(abs(x - t) <= 3.5 for x in ts_) >= 3
        before = max((t for t in others if t < lo and solid(others, t)), default=None)
        after = min((t for t in others if t > hi and solid(others, t)), default=None)
        out.append({"start": lo - 1.0, "end": hi + 1.0, "frames": len(best), "sep_before": before, "sep_after": after})
    return out


# ---------------------------------------------------------------- 音频：特征 + 边界精修

def features(c):
    """0.1s 一帧：mix_db 整场响度，voc_db 人声响度，flat 伴奏频谱平坦度（越低越像音乐）。缓存到 features.npz。"""
    if c.features.exists():
        f = np.load(c.features)
        if "voc_db" in f.files or not c.vocals.exists():  # 先于人声分离算的缓存，有了人声要重算
            return {k: f[k] for k in f.files}
    import librosa
    sr = 16000
    hop = int(sr * HOP)
    print("计算音频特征（整场，一次）...", flush=True)
    mix, _ = librosa.load(str(c.audio), sr=sr, mono=True)
    out = {}
    if c.vocals.exists():
        voc, _ = librosa.load(str(c.vocals), sr=sr, mono=True)
        n = min(len(mix), len(voc))
        mix, voc = mix[:n], voc[:n]
        inst = mix - voc
        out["voc_db"] = librosa.amplitude_to_db(librosa.feature.rms(y=voc, frame_length=hop * 2, hop_length=hop)[0], ref=1.0)
    else:
        inst = mix
    out["mix_db"] = librosa.amplitude_to_db(librosa.feature.rms(y=mix, frame_length=hop * 2, hop_length=hop)[0], ref=1.0)
    spec = np.abs(librosa.stft(inst, n_fft=2048, hop_length=hop)) + 1e-10
    band = spec[16:384]  # 约 125Hz ~ 3kHz：音乐的和声主要在这里，掌声在这里也接近白噪声
    out["flat"] = np.exp(np.log(band).mean(0)) / band.mean(0)
    n = min(len(v) for v in out.values())
    out = {k: v[:n].astype(np.float32) for k, v in out.items()}
    np.savez(c.features, **out)
    return out


def smooth(x, sec):
    k = max(1, int(sec / HOP))
    return np.convolve(x, np.ones(k) / k, mode="same")


class Audio:
    def __init__(self, f):
        self.mix = smooth(f["mix_db"], 1.0)
        self.flat = smooth(f["flat"], 1.5)
        self.voc = smooth(f["voc_db"], 0.5) if "voc_db" in f else None
        # 阈值按整场分布定：平坦度低于整场 60% 分位、响度高于 15% 分位，算「在奏乐」
        self.flat_thr = float(np.percentile(self.flat, 60))
        self.mix_thr = float(np.percentile(self.mix, 15))
        self.voc_thr = float(np.percentile(self.voc, 70)) if self.voc is not None else None
        self.music = (self.flat < self.flat_thr) & (self.mix > self.mix_thr)
        self.n = len(self.mix)

    def i(self, t):
        return int(np.clip(t / HOP, 0, self.n - 1))

    def walk(self, t, limit, step, allow=2.0):
        """从 t 出发朝 step 方向（±1）走，音乐断开超过 allow 秒就停，最多走到 limit。返回音乐的边缘时刻。"""
        i, lim = self.i(t), self.i(limit)
        edge, quiet = i, 0
        while (i - lim) * step < 0:
            i += step
            if self.music[i]:
                edge, quiet = i, 0
            else:
                quiet += 1
                if quiet * HOP > allow:
                    break
        return edge * HOP, (i - lim) * step >= 0

    def talking(self, t0, t1):
        """[t0, t1] 里人声活跃、但不在奏乐的时段的开头（讲话），没有返回 None。"""
        if self.voc is None or t1 <= t0:
            return None
        a, b = self.i(t0), self.i(t1)
        talk = (self.voc[a:b] > self.voc_thr) & ~self.music[a:b]
        hit = np.where(talk)[0]
        return (a + hit[0]) * HOP if len(hit) and talk.mean() > 0.15 else None

    def applause_end(self, t, limit):
        """t 之后响度回落到音乐阈值以下的时刻（掌声结束），最多 APPLAUSE_TAIL 秒。"""
        a, b = self.i(t), self.i(min(limit, t + APPLAUSE_TAIL))
        low = np.where(self.mix[a:b] < self.mix_thr + 6)[0]
        return (a + low[0]) * HOP if len(low) else b * HOP


def talk_before(talk, start, floor):
    """字幕轨里紧挨在 start 之前的讲话（相邻讲话间隔 < 8s 连成一段，最后一段离 start < 20s），返回讲话开头。"""
    t = None
    for s, e in sorted(talk, reverse=True):
        if s >= start - 1.0 or s < floor:   # 歌开始以后才开口的不算；讲话字幕可以延续到前奏里
            continue
        e = min(e, start)
        if (t is None and start - e < 20.0) or (t is not None and t - e < 8.0):
            t = s
        elif t is not None:
            break
    return t


def refine_edges(spans, titles, audio, duration, talk=None):
    """按顺序逐首定边界：开头不早于上一首结尾，结尾不晚于下一首开头。有歌名字幕用字幕时段，否则用音频规则。"""
    out, prev_end = [], 0.0
    for k, sp in enumerate(spans):
        if sp is None:
            out.append(None)
            continue
        ti = titles[k] if titles else None
        nxt_sp = next(((spans[j], titles[j] if titles else None) for j in range(k + 1, len(spans)) if spans[j]), None)
        nxt = duration if nxt_sp is None else (nxt_sp[1]["start"] if nxt_sp[1] else nxt_sp[0]["first"])
        flags = []
        if ti:
            # 歌名字幕有时晚出现（亮背景上 OCR 读不出）：字幕轨第一句更早、又没越过分隔帧，就用第一句
            # 歌名区域有时被转播的二维码推广条盖住、读不出：分隔帧（MADRID）一结束歌就开始了，
            # 两者相距不远（≤ SEP_GAP）就从分隔帧后面算起
            sep = ti["sep_before"]
            floor = max(prev_end, sep + 1.0 if sep is not None else 0.0)
            start = max(floor, min(ti["start"], sp["first"] - 2.0))
            if sep is not None and 0 < start - (sep + 1.0) <= SEP_GAP:
                start = max(prev_end, sep + 1.0)
        else:
            lo = max(prev_end, sp["first"] - MAX_INTRO)
            start, capped = audio.walk(sp["first"], lo, -1) if audio else (sp["first"] - 8.0, False)
            if capped and lo > prev_end:
                flags.append("前奏找不到起点（到了 50s 上限）")
            flags.append("没有歌名字幕，边界按音频估计")
        # 歌前讲话：有字幕轨用字幕里的讲话段（准），否则用音频（人声活跃且不在奏乐，粗）。
        # 比 MAX_TALK 长就整段都不并入（不从句子中间切开），只提示
        if talk is not None:
            ts = talk_before(talk, start, prev_end)
        else:
            ts = audio.talking(max(prev_end, start - MAX_TALK - 20), start) if audio else None
        if ts is not None and start - ts <= MAX_TALK:
            start = ts - 0.5
            flags.append("含歌前讲话")
        elif ts is not None:
            flags.append(f"歌前有 {start - ts:.0f}s 讲话，未并入")
        start = max(prev_end, start - 0.5)
        if ti:
            ceil = ti["sep_after"] - 1.0 if ti["sep_after"] is not None else nxt
            end = min(max(ti["end"], sp["last"] + 2.0), ceil)
            if ti["sep_after"] is not None and 0 < ceil - end <= 20.0:
                end = ceil
        else:
            hi = min(nxt - 1.0, sp["last"] + MAX_OUTRO)
            end, capped = audio.walk(sp["last"], hi, +1) if audio else (sp["last"] + 6.0, False)
            if capped and hi < nxt - 1.0:
                flags.append("尾奏找不到终点（到了 40s 上限）")
        end = audio.applause_end(end, nxt - 0.5) if audio else end
        end = max(min(end, nxt - 0.5), start + 1.0)   # 和下一首直接衔接时切在下一首开头之前
        out.append({"start": round(start, 2), "end": round(end, 2), "flags": flags})
        prev_end = out[-1]["end"]
    return out


def stage_segment(c, a):
    info = read_json(c.info)
    items = c.items()
    songs = [it for it in items if it["kind"] == "song"]
    lyrics = {}
    for it in songs:
        p = c.song_dir(it) / "lyrics.txt"
        lyrics[it["name"]] = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        if not lyrics[it["name"]]:
            print(f"⚠ {it['title']} 没有歌词，只能靠前后歌曲夹出位置")
    spans, talk = coarse_spans(c, songs, lyrics)
    audio = Audio(features(c)) if c.audio.exists() else None
    if audio and audio.voc is None:
        print("⚠ 还没有 vocals.wav：不判断歌前讲话（先跑 separate）")
    titles = title_spans(title_ocr(c), songs, spans) if c.source.exists() else None
    if titles:
        print(f"歌名字幕定位到 {sum(t is not None for t in titles)}/{len(songs)} 首")
    edges = refine_edges(spans, titles, audio, info["duration"], talk if c.captions.exists() else None)

    old = {x["name"]: x for x in (c.load("segments") or {}).get("items", [])}
    out = []
    for it, sp, ed in zip(songs, spans, edges):
        seg = {"idx": it["idx"], "name": it["name"], "title": it["title"], "kind": "song"}
        if sp is None:
            seg.update({"start": None, "end": None, "confidence": 0.0, "flags": ["字幕里没找到这首歌，需人工定位"]})
        else:
            n_lines = max(1, sum(len(norm(l)) >= MIN_LINE for l in lyrics[it["name"]]))
            conf = min(1.0, sp["hits"] / (0.6 * n_lines))
            seg.update({"start": ed["start"], "end": ed["end"], "lyric_start": round(sp["first"], 2),
                        "lyric_end": round(sp["last"], 2), "hits": sp["hits"], "confidence": round(conf, 2),
                        "flags": ed["flags"] + (["字幕证据少"] if conf < 0.35 else [])})
        prev = old.get(it["name"])
        if prev and prev.get("manual") and not a.force:
            seg.update({k: prev[k] for k in ("start", "end", "manual")})
            seg["flags"] = [f for f in seg["flags"] if "人工" not in f] + ["边界已人工调整"]
        out.append(seg)
    # 歌与歌之间的空档：按歌单标出过场名字，审核页时间轴用
    gaps = []
    for x, y in zip([None] + out, out + [None]):
        g0 = x["end"] if x and x["end"] is not None else 0.0
        g1 = y["start"] if y and y["start"] is not None else info["duration"]
        if g1 - g0 < 1.0:
            continue
        i0 = x["idx"] if x else 0
        i1 = y["idx"] if y else len(items) + 1
        tapes = [it["title"] for it in items if i0 < it["idx"] < i1]
        gaps.append({"start": round(g0, 2), "end": round(g1, 2), "interludes": tapes,
                     "talk": [[round(s, 1), round(e, 1)] for s, e in talk if g0 <= s < g1]})
    write_json(c.segments, {"items": out, "gaps": gaps})
    for s in out:
        if s["start"] is None:
            print(f"{s['idx']:>3} {s['title'][:30]:<30}  ⚠ 未定位")
            continue
        print(f"{s['idx']:>3} {s['title'][:30]:<30} {hms(s['start'])} - {hms(s['end'])} "
              f"({s['end'] - s['start']:5.0f}s) 置信 {s['confidence']:.2f}  {'；'.join(s['flags'])}")
    print(f"\n写入 {c.segments}")
