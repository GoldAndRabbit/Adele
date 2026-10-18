# -*- coding: utf-8 -*-
"""
回归检查：审核时指出过的每个问题写成一条检查，改对齐策略后先跑这 4 首，全部通过再跑全场。
时间都是单曲片段里的秒数（字幕显示时间，已含 0.2 s 提前）。

    .venv/bin/python tests/regression_shakira.py            # 4 首全查
    .venv/bin/python tests/regression_shakira.py 32_dai_dai # 只查一首
    加 --exp 查 v1 实验（exp/），加 --v2 查 v2 实验（exp_v2/）
"""

import re
import sys
import unicodedata
from pathlib import Path

import pysubs2

SONGS = Path(__file__).resolve().parent.parent / "concerts" / "shakira_madrid_2026" / "songs"


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", "".join(c for c in s if not unicodedata.combining(c)))).strip()


POSTS = Path(__file__).resolve().parent.parent / "posts"


def load(song, exp=""):
    """exp="" 查正式字幕（v0），"exp" 查 v1 实验，"exp_v2" 查 v2 实验。"""
    base = (POSTS / song) if (POSTS / song).exists() and not (SONGS / song).exists() else SONGS / song
    subs = pysubs2.load(str(base / (f"{exp}/lyrics.srt" if exp else "lyrics.srt")))
    ev = list(subs.events)
    if exp and (base / exp / "speech.srt").exists():   # v2 的讲话单独一个文件（黄色），画面上一样会出现
        ev += pysubs2.load(str(base / exp / "speech.srt")).events
    return sorted((e.start / 1000, e.end / 1000, e.plaintext.strip()) for e in ev)


def find(lines, pat, lo=0, hi=1e9):
    return [x for x in lines if lo <= x[0] <= hi and re.search(pat, norm(x[2]))]


def has(pat, lo, hi, why):
    return lambda L: (bool(find(L, pat, lo, hi)), why, find(L, pat, lo - 5, hi + 5)[:3])


def lacks(pat, lo, hi, why):
    return lambda L: (not find(L, pat, lo, hi), why, find(L, pat, lo, hi)[:3])


def count(pat, lo, hi, n, why):
    return lambda L: (len(find(L, pat, lo, hi)) >= n, why, find(L, pat, lo, hi))


def order(pats, lo, hi, why):
    def f(L):
        ts = []
        for p in pats:
            m = find(L, p, lo, hi)
            if not m:
                return False, why, f"缺 {p}"
            ts.append(m[0][0])
        return ts == sorted(ts), why, list(zip(pats, ts))
    return f


def each_own_line(names, lo, hi, why):
    def f(L):
        miss, crowded = [], []
        for n in names:
            m = find(L, n, lo, hi)
            if not m:
                miss.append(n)
            elif len(norm(m[0][2]).split()) > 3:
                crowded.append(m[0][2])
        return not miss and not crowded, why, {"缺": miss, "没拆开": crowded}
    return f


def no_text(pat, why):
    return lambda L: (not [x for x in L if re.search(pat, x[2])], why, [x for x in L if re.search(pat, x[2])][:3])


def short_lines(max_words=14):
    long = lambda L: [x for x in L if len(x[2].split()) > max_words]
    return lambda L: (not long(L), f"一行字幕不超过 {max_words} 个词（整段没标点时会连成一整屏）", long(L)[:2])


CHECKS = {
    "04_girl_like_me": [
        lacks(r".", 4.5, 30, "开头没唱（片头歌名之后到 30 s）不出字幕"),
        has(r"you're lookin' for", 58.5, 62.5, "1:00 左右「Ah-ah-ah, you're lookin' for」要有字幕（之前被复核误隐藏）"),
        has(r"sha sha shakira", 80, 92, "1:23 左右「Sha-Sha-Shakira」"),
        each_own_line(["venezolana", "ecuatoriana", "puertorrique", "dominicana", "argentin", "brasile", "bolivian",
                       "chilena", "peruana", "cubana", "espanola", "colombiana"], 96, 121,
                      "报国家名一个名字一行，不能漏 ecuatoriana / argentinas"),
        lacks(r"^latinas latinas$", 102, 108, "1:44 唱的是国家名，不是「Latinas, latinas」"),
        lacks(r"americana", 95, 125, "「Americana」是上一句 Dominicana 的尾音，不是歌词"),
    ],
    "32_dai_dai": [
        lacks(r"em polo|like the name|always see it solid", 0, 30, "开头人群声里的幻听讲话不出字幕"),
        count(r"oh eh", 38, 56, 1, "0:42~0:54 唱「Oh-eh-oh-eh」要有字幕"),
        has(r"you knew from the day", 52, 56, "0:54「You knew from the day you were born」"),
        has(r"^dale$", 190.8, 192.6, "3:11 左右的「Dale」不能太早（之前早 2 s）也不能太晚"),
        order([r"^dale$", r"no olvide", r"juega como tu sabes"], 188, 200, "Dale → No olvide' lo que vales → Juega como tú sabes 顺序"),
        has(r"juega como tu sabes", 192, 198, "3:13 左右「Juega como tú sabes」"),
        has(r"mas fuerte", 200, 207, "3:24 左右「Oe, oe, más fuerte」"),
        has(r"como tu sabes? como tu sabes?", 130, 140, "2:14 左右连唱两遍「Como tú sabes, como tú sabes」"),
    ],
    "33_waka_waka_esto_es_africa": [
        count(r"zangalewa", 16, 31, 3, "0:17~0:29「Uh, zangalewa (Otra, otra)」要有字幕（之前整段空着）"),
        lacks(r"ahora vamos por todo", 0, 22, "开头人群喊「¡Vamos!」不是「Ahora vamos por todo」"),
        has(r"llego el momento", 27, 32, "0:29「Llegó el momento, caen las murallas」"),
    ],
    "37_bzrp_music_sessions_53": [
        lacks(r"por aca no vuelva", 3, 12, "开头「Ah, ah」不是「Por acá no vuelva', hazme caso」"),
        has(r"perdon ya cogi otro avion", 38.5, 44, "0:41「Perdón, ya cogí otro avión」"),
        has(r"aqui no vuelvo", 42, 46, "0:43「Aquí no vuelvo, no quiero otra decepción」"),
        has(r"mortifique", 87, 94, "1:30「Esto es pa' que te mortifique', mastique' y trague'…」"),
        has(r"culpa mia que te critiquen", 95, 102, "1:39「Entendí que no es culpa mía que te critiquen」"),
        no_text(r"[Ѐ-ӿ]|Pas si fort", "不能有俄语 / 法语幻听"),
    ],
    "sara_perche_1983": [
        has(r"primavera sara perche ti amo", 37, 41, "0:38「È primavera, sarà perché ti amo」（之前 sarà perché ti amo 被并到下一句）"),
        has(r"cade una stella", 41, 44, "0:42「Cade una stella, ma dimmi dove siamo」"),
    ],
    "sara_perche_zarrella2023": [],
    "ricchi_sanremo2020_medley": [
        has(r"stringimi forte", 18, 32, "0:2x「Stringimi forte e stammi più vicino」单独一行（之前和后面几句连成一整屏）"),
    ],
    "lose_yourself_2009": [],
    "sobaniirune": [],
    "hkt48_sobaniirune": [],
}
for _song in CHECKS:
    CHECKS[_song].append(short_lines())


def main():
    only = [x for x in sys.argv[1:] if not x.startswith("--")]
    total = bad = 0
    for song, checks in CHECKS.items():
        if only and song not in only:
            continue
        L = load(song, exp="exp_v2" if "--v2" in sys.argv else "exp" if "--exp" in sys.argv else "")
        print(f"\n== {song}（{len(L)} 句）")
        for c in checks:
            ok, why, detail = c(L)
            total += 1
            bad += not ok
            print(f"  {'✓' if ok else '✗'} {why}" + ("" if ok else f"\n      实际：{detail}"))
    print(f"\n{total - bad}/{total} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
