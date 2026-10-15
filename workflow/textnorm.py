# -*- coding: utf-8 -*-
"""文本归一化：比较歌词文字和识别结果时，统一转成平假名读音（汉字/假名写法不同也能对上）。"""

import unicodedata

import pykakasi

_kks = pykakasi.kakasi()


def norm_char(c):
    c = unicodedata.normalize("NFKC", c).lower()
    if "ァ" <= c <= "ヶ":  # 片假名 -> 平假名
        c = chr(ord(c) - 0x60)
    return c if (c.isalnum() or "぀" <= c <= "ヿ") else ""


def reading(text):
    """文本 -> 归一化的平假名读音串（英文保留小写字母和数字）。"""
    out = "".join(item["hira"] or item["orig"] for item in _kks.convert(text))
    return "".join(norm_char(c) for c in out)
