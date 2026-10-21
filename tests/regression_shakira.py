# -*- coding: utf-8 -*-
"""
回归检查：审核时指出过的每个问题写成一条检查，改对齐策略后先跑这 4 首，全部通过再跑全场。
时间都是单曲片段里的秒数（字幕显示时间，已含 0.2 s 提前）。

    .venv/bin/python tests/regression_shakira.py            # 4 首全查
    .venv/bin/python tests/regression_shakira.py 32_dai_dai # 只查一首
"""

import re
import sys
import unicodedata
from pathlib import Path

import pysubs2

SONGS = Path(__file__).resolve().parent.parent / "concerts" / "shakira_madrid_2026" / "songs"
POSTS = Path(__file__).resolve().parent.parent / "posts"


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", "".join(c for c in s if not unicodedata.combining(c)))).strip()


def load(song):
    """查视频里实际显示的字幕文件 subs/lyrics.ass（翻译阶段去掉的幻听、顶部注释、片头歌名都按最终结果算）。
    返回 [(起, 止, 文字, 是不是讲话)]。"""
    base = SONGS / song if (SONGS / song).exists() else POSTS / song   # 单曲在 posts/<歌名>/
    out = []
    for e in pysubs2.load(str(base / "subs" / "lyrics.ass")).events:
        first = pysubs2.SSAEvent(text=e.text.replace("\\n", "\\N").split("\\N")[0]).plaintext.strip()
        if e.style in ("Default", "Speech") and first and not first.startswith("《"):
            out.append((e.start / 1000, e.end / 1000, first, e.style == "Speech"))
    return sorted(out)


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


def has_raw(pat, lo, hi, why):
    """原文匹配（日文等，norm 会把非拉丁字母去掉）。"""
    f = lambda L: [x for x in L if lo <= x[0] <= hi and re.search(pat, x[2])]
    return lambda L: (bool(f(L)), why, [x[:3] for x in L if lo - 5 <= x[0] <= hi + 5][:4])


def no_raw(pat, why):
    bad = lambda L: [x[:3] for x in L if re.search(pat, x[2])]
    return lambda L: (not bad(L), why, bad(L)[:3])


def all_speech(lo, hi, why, pat=None):
    """[lo, hi] 里（匹配 pat 的）每一行都是讲话（黄色），而且至少有一行。"""
    def f(L):
        xs = [x for x in L if lo <= x[0] <= hi and (pat is None or re.search(pat, norm(x[2])))]
        bad = [x[:3] for x in xs if not x[3]]
        return bool(xs) and not bad, why, bad[:4] or (xs[:2] if xs else "这段没有字幕")
    return f


def short_raw(max_chars, lo, hi, why):
    """日文一行不超过 max_chars 个字（不连成一整屏）。"""
    bad = lambda L: [x[:3] for x in L if lo <= x[0] <= hi and len(re.sub(r"\s", "", x[2])) > max_chars]
    return lambda L: (not bad(L), why, bad(L)[:2])


INTERJ_TOK = re.compile(r"^\W*(?:(?:oh|uh|ah|eh|ay|yeah|hey|na|la|mm)\W*)+$", re.I)


def short_lines(max_words=14):
    # 语气词（uh-uh-uh-uh）不算词数：Genius 原句后面带的语气词留在同一行
    long = lambda L: [x for x in L if len([w for w in x[2].split() if not INTERJ_TOK.match(w)]) > max_words]
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
        # 2026-10-20 起点往后挪了 30 s（前 30 s 人群声 / 幻听切掉），下面的时间都是新起点下的
        count(r"oh eh", 8, 26, 1, "0:12~0:24 唱「Oh-eh-oh-eh」要有字幕"),
        has(r"knew from the day you were born", 22, 26, "0:24「(You) knew from the day you were born」（Genius 前后两处写法不同，现场把结尾那段搬到了开头）"),
        has(r"^dale$", 160.8, 162.6, "2:41 左右的「Dale」不能太早（之前早 2 s）也不能太晚"),
        order([r"^dale$", r"no olvide", r"juega como tu sabes"], 158, 170, "Dale → No olvide' lo que vales → Juega como tú sabes 顺序"),
        has(r"juega como tu sabes", 162, 168, "2:43 左右「Juega como tú sabes」"),
        has(r"mas fuerte", 170, 177, "2:54 左右「Oe, oe, más fuerte」"),
        has(r"como tu sabes? como tu sabes?", 100, 110, "1:44 左右连唱两遍「Como tú sabes, como tú sabes」"),
    ],
    "33_waka_waka_esto_es_africa": [
        count(r"zangalewa", 16, 31, 3, "0:17~0:29「Uh, zangalewa (Otra, otra)」要有字幕（之前整段空着）"),
        lacks(r"ahora vamos por todo", 0, 22, "开头人群喊「¡Vamos!」不是「Ahora vamos por todo」"),
        has(r"llego el momento", 27, 32, "0:29「Llegó el momento, caen las murallas」"),
    ],
    "37_bzrp_music_sessions_53": [
        has(r"claramente no es como suena", 186, 192, "3:08「Claramente no es como suena」（不是又一遍 Tiene nombre…）"),
        has(r".", 211, 235, "3:31~3:55 有字幕（识别整段漏掉的地方）"),
        has(r"con la prensa", 276, 283, "4:38「Con la prensa en la puerta…」（观众合唱，识别成 La suegra y la vecina）"),
        has(r"las mujeres ya no lloran", 284, 292, "4:46「Las mujeres ya no lloran…」（识别成 Más dura）"),
        count(r"tipos como tu", 290, 300, 2, "4:52、4:56「Pa' tipos como tú」两遍"),
        has(r"a ti te quede grande", 298, 307, "5:00「A ti te quedé grande…」"),
        lacks(r"^oh oh", 295, 310, "5:00 不能补成「Oh-oh」"),
        lacks(r"^uh uh uh uh$", 0, 400, "「uh-uh-uh-uh」不单独成行"),
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
    "lose_yourself_2009": [
        all_speech(4, 29, "开场「Hey yo … Keep your heads up」全部是讲话（黄色）"),
        all_speech(285, 312, "结尾致谢（Thank you / Everybody for coming out tonight / Peace）全部是讲话",
                   pat=r"thank|everybody|noise|peace|detroit|love you"),
        lacks(r"^yo$", 280, 312, "结尾致谢里的「you」不能配成歌词「Yo」"),
        lacks(r"mom i love you", 300, 312, "结尾「man we love you」不能配成「Mom, I love you…」"),
    ],
    "sobaniirune": [
        all_speech(6, 30, "0:06~0:30 开场对话（久しぶり / 元気？…）全部是讲话（黄色）"),
        no_raw(r"(心の中では).*\1", "1:00「心の中では…」不能在一条字幕里出现两遍"),
    ],
    "hkt48_sobaniirune": [
        has_raw(r"あなたのこと", 10, 15, "0:11「あなたのこと私は今でも」对上 Genius"),
        has_raw(r"思い続けているよ", 13, 19, "0:15「思い続けているよ」"),
        has_raw(r"心の中では", 26.5, 29.5, "0:27「心の中では」开头在 0:27~0:29（不是 0:32）"),
        short_raw(30, 135, 200, "2:15~3:20 每句一行，不连成一整屏（一行不超过 30 字）"),
    ],
}
for _song in CHECKS:
    CHECKS[_song].append(short_lines())


def main():
    only = [x for x in sys.argv[1:] if not x.startswith("--")]
    total = bad = 0
    for song, checks in CHECKS.items():
        if only and song not in only:
            continue
        L = load(song)
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
