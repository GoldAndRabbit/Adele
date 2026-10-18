# -*- coding: utf-8 -*-
"""
refine：逐首精校字幕。只切音频（不切视频）：按 segments.json 从整场 audio.flac / vocals.wav 切出这首的片段，
然后完全走 v1 的流程（make_mv.py，ADELE_POSTS 指向 songs/，在 songs/<nn>/ 上跑），字幕时间以片段起点为 0：
  Qwen 窗口识别（v1 qwen_dense 缓存）-> 演唱会排序（concert_align.py：不补没唱的句子、长句优先、拆重复句、MMS ±1s）
  -> 空档补词（gap_fill.py：歌词网站上没有的现场词，Qwen 识别 + MMS 逐词对齐）-> v1 verify_qwen（逐句 Qwen 复核，低于 45 分的隐藏）
  -> speech（讲话，去掉人群声里编出来的纯语气词）-> translate
注意：直播字幕轨不能当对齐 / 检查的依据——它的延迟忽长忽短（-2~+8s），说唱段像是提前打好的稿，和实际演唱对不上。
"""

import contextlib
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from .paths import ROOT, VENV_PY, read_json, write_json
from .util import hms, run

ALIGN = "concert-v23"  # song.json 里记的对齐方式；改了方式就会重跑
HIDE_BELOW = 45       # 逐句 Qwen 复核低于这个分隐藏（v1 默认 30；演唱会尾奏 / 讲话里误配的句子在 33~44，真唱没听清的在 50~65）
JOBS = 1  # 一次精校一首：每首内部已有 3 路 Qwen 并发，多首并行会触发 429 限流，缺识别证据导致对齐出错


def selected(c, a):
    sel = set(a.songs) if getattr(a, "songs", None) else None
    segs = {s["name"]: s for s in (c.load("segments") or {}).get("items", [])}
    out = []
    for it in c.song_items():
        if sel and not ({it["name"], str(it["idx"]), f"{it['idx']:02d}"} & sel):
            continue
        seg = segs.get(it["name"])
        if not seg or seg.get("start") is None:
            print(f"{it['idx']:>2} {it['title']}: 没有定位（segments.json），跳过")
            continue
        if not (c.song_dir(it) / "lyrics.txt").exists():
            print(f"{it['idx']:>2} {it['title']}: 没有歌词，跳过")
            continue
        out.append((it, seg))
    return out


def shift_cache(d, old, new):
    """边界改了：Qwen 窗口识别缓存（片段内时间 -> 文字）按起点位移平移过去，不用重新识别整首。
    位移不是 0.5s 的整数倍（窗口网格对不上）或没有旧边界时删掉重来。"""
    cache = d / "reports" / "dense_cache.json"
    if not cache.exists():
        return
    delta = (new[0] - old[0]) if old else None
    if delta is None or abs(delta * 2 - round(delta * 2)) > 1e-6:
        cache.unlink()
        return
    import json
    c = json.loads(cache.read_text())
    dur = new[1] - new[0]
    moved = {f"{float(k) - delta:.2f}": v for k, v in c.items() if 0 <= float(k) - delta <= dur - 2.5}
    cache.write_text(json.dumps(moved, ensure_ascii=False))


def cut_audio(c, it, seg, force=False):
    """片段边界变了就重切，并清掉依赖旧时间轴的结果（翻译缓存 zh_cache.json 保留，不用重翻）。"""
    d = c.song_dir(it)
    info = read_json(d / "song.json", {})
    span = [round(seg["start"], 2), round(seg["end"], 2)]
    if info.get("slice") == span and (d / "audio.flac").exists() and (d / "vocals.wav").exists() and not force:
        return False
    shift_cache(d, info.get("slice"), span)
    for f in ("lyrics.srt", "speech.srt", "lyrics.ass", "subs.ass", "reports/verify_report.json"):
        (d / f).unlink(missing_ok=True)
    trim = ["-ss", f"{span[0]:.3f}", "-to", f"{span[1]:.3f}"]
    run(["ffmpeg", "-v", "error", "-y", *trim, "-i", c.audio, "-c:a", "flac", "-ar", "48000", "-sample_fmt", "s32",
         d / "audio.flac"])
    run(["ffmpeg", "-v", "error", "-y", *trim, "-i", c.vocals, "-c:a", "pcm_s16le", d / "vocals.wav"])
    info["slice"] = span
    write_json(d / "song.json", info)
    return True


def sub_title(c, it):
    artist = read_json(c.info).get("artist", "")
    return f"《{it['title']}》 {artist}".strip()


# 新流程（align2）还在实验目录里调，审核页上的歌全部用原流程；ADELE_ALIGN2=1 时才走新流程
GLOBAL = {"04_girl_like_me", "32_dai_dai", "33_waka_waka_esto_es_africa", "37_bzrp_music_sessions_53"} \
    if os.environ.get("ADELE_ALIGN2") == "1" else set()
GLOBAL_ALIGN = "global-v6"   # align2.py：整首转写 + 全局序列对齐 + 声学定时（先在这 4 首上验证）


def refine_global(c, it, seg, a):
    """新流程（align2.py，原因见 docs/design/v2_alignment_root_causes.md）：
    整首转写 → 歌词全局对齐 → MMS 声学定时 → 逐句 Qwen 复核只标红 → 讲话 → 翻译。"""
    from . import align2
    import acoustic
    d = c.song_dir(it)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    changed = cut_audio(c, it, seg, a.force)
    from .preview import make_preview
    make_preview(c, it, seg)
    info = read_json(d / "song.json", {})
    if not changed and not a.force and (d / "lyrics.ass").exists() and info.get("align") == GLOBAL_ALIGN:
        print(f"{it['idx']:>2} {it['title']}: 已精校（边界没变；--force 重跑）", flush=True)
        return True
    lang = "auto" if len(info.get("langs") or []) > 1 else info.get("lang", "en")
    os.environ["QWEN_CACHE"] = str(d / "reports" / "qwen_cache.json")
    env = dict(os.environ, ADELE_POSTS=str(c.songs))
    base = [VENV_PY, ROOT / "workflow" / "make_mv.py", "--name", it["name"], "--lang", lang, "--title", sub_title(c, it)]
    tr = (["--force"] if a.force else []) + (["--retranslate"] if getattr(a, "retranslate", False) else [])
    log = d / "logs" / "v2_refine.log"
    log.parent.mkdir(exist_ok=True)
    print(f"{it['idx']:>2} {it['title']}: 精校开始（全局对齐，{hms(seg['start'])} - {hms(seg['end'])}，日志 {log}）", flush=True)
    srt, rep = d / "lyrics.srt", d / "reports"
    shutil.rmtree(rep / "stages", ignore_errors=True)   # 旧流程的分步快照
    with log.open("w") as fh:
        def sh(cmd, **kw):
            return subprocess.run([str(x) for x in cmd], stdout=fh, stderr=subprocess.STDOUT, **kw)
        lyr = [t for t, _ in acoustic.section_lines(d / "lyrics.txt")]
        with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
            items = align2.align(d, lang, srt, lyr)
        n_l = sum(1 for x in items if x["kind"] == "lyric")
        print(f"全局对齐：{len(items)} 句（Genius {n_l}，现场 {len(items) - n_l}）", file=fh, flush=True)
        # 逐句复核：只出报告（听到的文字 + 可疑分），字幕不改
        tmp = rep / "verify_out.srt"
        r = sh([VENV_PY, ROOT / "workflow" / "verify_qwen.py", srt, "--ref", d / "lyrics.txt", "--vocals", d / "vocals.wav",
                "--lang", lang, "--no-swap", "--hide-below", "0", "-o", tmp, "--report", rep / "verify_report.json"])
        tmp.unlink(missing_ok=True)
        align2.write_lines(d, items, read_json(rep / "verify_report.json", {}) or {})
        if r.returncode == 0:
            info["align"] = GLOBAL_ALIGN
            write_json(d / "song.json", info)
            r = sh([VENV_PY, ROOT / "workflow" / "make_mv.py", "--name", it["name"], "--lang", "auto",
                    "--title", sub_title(c, it), "--from", "speech", "--to", "speech"], env=env)
        if r.returncode == 0:
            filter_speech(c, it, seg)
            (d / "lyrics.ass").unlink(missing_ok=True)
            r = sh(base + ["--from", "translate", "--to", "translate"] + tr, env=env)
    if r.returncode:
        print(f"{it['idx']:>2} {it['title']}: ✗ 失败（exit {r.returncode}），见 {log}", flush=True)
        return False
    print(f"{it['idx']:>2} {it['title']}: ✓ {len(items)} 句（Genius {n_l}，现场 {len(items) - n_l}）", flush=True)
    return True


def refine_one(c, it, seg, a):
    if it["name"] in GLOBAL:
        return refine_global(c, it, seg, a)
    d = c.song_dir(it)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    changed = cut_audio(c, it, seg, a.force)
    from .preview import make_preview
    make_preview(c, it, seg)   # 边界改了预览视频也要跟着重切
    info = read_json(d / "song.json", {})
    if not changed and not a.force and (d / "lyrics.ass").exists() and info.get("align") == ALIGN:
        print(f"{it['idx']:>2} {it['title']}: 已精校（边界没变；--force 重跑）", flush=True)
        return True
    # 串烧里几首语言不同（Empire 英语 / Inevitable 西语）：Qwen 不指定语言，否则另一种语言的段落认不出来
    lang = "auto" if len(info.get("langs") or []) > 1 else info.get("lang", "en")
    # Qwen 识别缓存（reports/qwen_cache.json）：同一段音频只识别一次，重跑不会每次换一种听法；边界改了音频不同，自然重新识别
    os.environ["QWEN_CACHE"] = str(d / "reports" / "qwen_cache.json")
    env = dict(os.environ, ADELE_POSTS=str(c.songs))
    base = [VENV_PY, ROOT / "workflow" / "make_mv.py", "--name", it["name"], "--lang", lang, "--title", sub_title(c, it)]
    tr = (["--force"] if a.force else []) + (["--retranslate"] if getattr(a, "retranslate", False) else [])
    log = d / "logs" / "v2_refine.log"
    log.parent.mkdir(exist_ok=True)
    print(f"{it['idx']:>2} {it['title']}: 精校开始（{hms(seg['start'])} - {hms(seg['end'])}，日志 {log}）", flush=True)
    srt, rep = d / "lyrics.srt", d / "reports"
    # 每一步之后存一份字幕快照（reports/stages/NN_步骤.srt），provenance.py 据此算出每句是哪一步来的、被哪一步改过
    stages = rep / "stages"
    shutil.rmtree(stages, ignore_errors=True)
    stages.mkdir(parents=True, exist_ok=True)

    def stage(name):
        if srt.exists():
            shutil.copy(srt, stages / f"{len(list(stages.glob('*.srt'))) + 1:02d}_{name}.srt")
    with log.open("w") as fh:
        def sh(cmd, **kw):
            return subprocess.run([str(x) for x in cmd], stdout=fh, stderr=subprocess.STDOUT, **kw)
        py = [VENV_PY]
        r = subprocess.CompletedProcess([], 0)
        # 1) Qwen 2.5s 窗口识别（v1 qwen_dense 的缓存）：没有缓存就先跑一遍 v1 dense 对齐生成
        if not (rep / "dense_cache.json").exists():
            r = sh(base + ["--from", "align", "--to", "align"], env=env)
        # 2) 演唱会排序 DP + 拆重复句 + MMS ±1s 精修（concert_align.py）
        if r.returncode == 0:
            from . import concert_align
            try:
                with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
                    n = concert_align.align(d, lang, srt)
                print(f"演唱会对齐：{n} 句", file=fh, flush=True)
                stage("align")
            except Exception as e:  # noqa: BLE001
                print(f"演唱会对齐失败：{e}", file=fh, flush=True)
                r = subprocess.CompletedProcess([], 1)
        # 3) 空档补词：现场改词 / 歌词网站上没有的段落，Qwen 整段识别 + MMS 逐词对齐补进字幕（gap_fill.py）
        if r.returncode == 0:
            from . import gap_fill
            import acoustic
            try:
                with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
                    k = gap_fill.fill(d, srt, lang, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")])
                print(f"空档补词：{k} 句", file=fh, flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"空档补词失败（跳过）：{e}", file=fh, flush=True)
            stage("fill")
        # （不再做 v1 refine_timing 整首全局对齐：上一句缺失时会把下一句的开头拉早好几秒；
        #   也不做 v1 acoustic 后处理：它只认参考歌词，会动到补进来的现场词）
        # 5) v1 逐句 Qwen 复核：只隐藏听不出来的句子（片段开头的讲话、前奏里的误配），不换句
        if r.returncode == 0:
            r = sh(py + [ROOT / "workflow" / "verify_qwen.py", srt, "--ref", d / "lyrics.txt", "--vocals", d / "vocals.wav",
                         "--lang", lang, "--no-swap", "--hide-below", str(HIDE_BELOW), "-o", srt,
                         "--report", rep / "verify_report.json"])
            stage("verify")
        # 6) 被复核隐藏的句子带上前后文再听一遍，听得出就放回来；现场改词：复核听到的和字幕完全不是一回事（Latinas -> Americana, Argentina）、或补词漏了词，换成实际唱的
        if r.returncode == 0:
            from . import gap_fill
            import acoustic
            try:
                lyr = [t for t, _ in acoustic.section_lines(d / "lyrics.txt")]
                with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
                    for x in gap_fill.drop_misplaced(d, srt):
                        print(f"去掉错位句 @{x['start']}s：{x['text']}（复核只听到：{x['heard']}）", file=fh, flush=True)
                    stage("drop")
                    for x in gap_fill.fill_expected(d, srt, lang, lyr):
                        print(f"补词换成该唱的歌词 @{x['start']}s：{x['was']} -> {x['text']}（{x['cover']:.0%}）", file=fh, flush=True)
                    stage("expected")
                    for x in gap_fill.snap_runs(d, srt, lang, lyr):
                        print(f"补词换成歌词 @{x['start']}s：{x['was']} -> {x['text']}", file=fh, flush=True)
                    stage("snap")
                    for x in gap_fill.rescue_hidden(d, srt, lang, lyr):
                        print(f"放回 @{x['start']}s：{x['text']}（前后文一起听：{x['heard']}）", file=fh, flush=True)
                    stage("rescue")
                    adopted = gap_fill.adopt_heard(d, srt, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")], lang)
                for x in adopted:
                    print(f"现场改词 @{x['start']}s：{x['was']} -> {x['text']}", file=fh, flush=True)
                stage("adopt")
            except Exception as e:  # noqa: BLE001
                print(f"现场改词失败（跳过）：{e}", file=fh, flush=True)
        if r.returncode == 0:
            # 没字幕的空档：按歌词顺序该唱的句子，窗口里听到了关键词就补上
            try:
                with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
                    for x in gap_fill.fill_gaps_expected(d, srt, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")]):
                        print(f"空档补该唱的句子 @{x['start']}-{x['end']}s：{x['text']}", file=fh, flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"空档补句失败（跳过）：{e}", file=fh, flush=True)
            stage("gaps")
            # 纯语气词的歌词句（Oh-eh-oh-eh）：对齐不打分，按歌词顺序排进前面听到语气词的空档
            try:
                with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
                    for x in gap_fill.fill_interjections(d, srt, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")]):
                        print(f"补语气词句 @{x['start']}-{x['end']}s：{x['text']}", file=fh, flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"补语气词句失败（跳过）：{e}", file=fh, flush=True)
            stage("interj")
            ext = gap_fill.extend_chants(d, srt)
            if ext:
                print(f"口号句往前延伸：{ext}", file=fh, flush=True)
            stage("extend")
            # 7) 列举句（报国家名）一项一句
            try:
                with contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
                    for x in gap_fill.split_lists(d, srt, lang):
                        print(f"列举句拆开 @{x['start']}s：{x['text']} -> {x['pieces']}", file=fh, flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"列举句拆分失败（跳过）：{e}", file=fh, flush=True)
            stage("split")
            # 8) 每句统一提前 0.2s 出现（对齐的、补进来的、拆开的都一样）
            gap_fill.lead_all(d, srt)
            stage("lead")
        if r.returncode == 0:
            info["align"] = ALIGN
            write_json(d / "song.json", info)
            # 讲话的语言不一定是歌的语言（马德里场讲西语），强制按歌的语言会把 Gracias 识别成 Thank you
            r = sh([VENV_PY, ROOT / "workflow" / "make_mv.py", "--name", it["name"], "--lang", "auto",
                    "--title", sub_title(c, it), "--from", "speech", "--to", "speech"], env=env)
        if r.returncode == 0:
            filter_speech(c, it, seg)
            # 讲话每次都重新识别、过滤，lyrics.ass 跟着重建（译文在 zh_cache.json 里，不会重翻）
            (d / "lyrics.ass").unlink(missing_ok=True)
            r = sh(base + ["--from", "translate", "--to", "translate"] + tr, env=env)
        if r.returncode == 0:
            from . import provenance
            import acoustic
            provenance.build(d, [t for t, _ in acoustic.section_lines(d / "lyrics.txt")])
    if r.returncode:
        print(f"{it['idx']:>2} {it['title']}: ✗ 失败（exit {r.returncode}），见 {log}", flush=True)
        return False
    v = read_json(rep / "verify_report.json", {})
    sus = v.get("suspect", [])
    print(f"{it['idx']:>2} {it['title']}: ✓ 隐藏 {sum(1 for x in sus if x.get('hidden'))} 句，"
          f"可疑 {sum(1 for x in sus if not x.get('hidden'))} 句", flush=True)
    return True


INTERJ = {"ah", "oh", "eh", "uh", "uhh", "ahh", "ohh", "mm", "mmm", "hm", "hmm", "ay", "hey", "yeah", "wow", "woo",
          "la", "na", "brr", "prr", "rrr", "aplausos", "applause", "musica", "music", "risas", "laughter", "gritos"}


def recheck_speech(d, events):
    """噪声里识别出来的「讲话」前后不一致：每句换两种起止再让 Qwen 听，
    对不上（< 70）就当幻听去掉；真说的话每次都能听出差不多的内容。"""
    if not events:
        return events
    import librosa
    import llm
    from openai import OpenAI
    from qwen_asr import ENDPOINT, SR, transcribe
    from rapidfuzz import fuzz
    from .segment import norm
    llm.load_env()
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    y, _ = librosa.load(str(d / "vocals.wav"), sr=SR, mono=True)
    out = []
    for e in events:
        # 两遍（前后各多 0.4s、0.8s）都要对得上（≥ 70）：人群声里的幻听每次听法都不一样
        # （Dai Dai 开头的「em polo polo ou papai」「I always see it solid」单复听一遍能蒙混过去）
        ok = True
        for pad in (0.4, 0.8):
            s, t = max(0.0, e.start / 1000 - pad), e.end / 1000 + pad
            again = transcribe(client, y[int(s * SR):int(t * SR)], "auto") or ""
            if fuzz.partial_ratio(norm(e.plaintext), norm(again)) < 70:
                ok = False
                break
        if ok:
            out.append(e)
    return out


def filter_speech(c, it, seg):
    """v1 的讲话识别在演唱会前奏 / 尾奏的人群声里会编出「¡Aplausos!」「¡Ah!」这类句子：纯语气词、拟声、舞台说明去掉。"""
    import pysubs2
    from .segment import norm
    d = c.song_dir(it)
    path = d / "speech.srt"
    if not path.exists():
        return
    if not path.read_text(encoding="utf-8").strip():  # 没识别到讲话时 v1 写的是空文件
        path.unlink()
        return
    subs = pysubs2.load(str(path))
    keep, report = [], []
    for e in subs.events:
        toks = norm(e.plaintext).split()
        junk = not toks or all(t in INTERJ or set(t) <= set("brpmhaoeu") for t in toks)
        # 西语 / 英语演唱会里冒出来的中日文（「哈哈」「嗯」）：识别幻听
        cjk_song = (read_json(d / "song.json", {}).get("lang") in ("zh", "ja"))
        junk = junk or (not cjk_song and re.search(r"[\u3400-\u9fff\u3040-\u30ff]", e.plaintext) is not None)
        report.append({"start": e.start / 1000, "text": e.plaintext, "keep": not junk})
        if not junk:
            keep.append(e)
    # 片头歌名卡（0~4s）期间的「讲话」：片段从上一首结尾的人群声切进来，多是幻听（Dai Dai「Like the name, Eep, Ahh」）
    keep = [e for e in keep if e.end > 4000]
    keep = recheck_speech(d, keep)
    subs.events = keep
    if keep:
        subs.save(str(path))
    else:
        path.unlink()  # 空 srt 后面 pysubs2 读不了；translate 只在 speech.srt 存在时带上讲话
    write_json(d / "reports" / "speech_filter.json", report)


def stage_refine(c, a):
    if not c.vocals.exists():
        sys.exit("缺少整场人声 vocals.wav，先跑 separate")
    todo = selected(c, a)
    def safe(x):
        try:
            return refine_one(c, *x, a)
        except Exception as e:  # noqa: BLE001 一首出错不影响其他歌
            print(f"{x[0]['idx']:>2} {x[0]['title']}: ✗ {type(e).__name__}: {e}", flush=True)
            return False
    with ThreadPoolExecutor(JOBS) as ex:
        res = list(ex.map(safe, todo))
    bad = [it["title"] for (it, _), ok in zip(todo, res) if not ok]
    print(f"\nrefine：{len(todo) - len(bad)}/{len(todo)} 首完成" + (f"；失败：{', '.join(bad)}" if bad else ""))
