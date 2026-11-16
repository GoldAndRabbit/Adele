"""Chinese fan names used in posting copy, in preferred display order."""
import re
import unicodedata

NICKNAMES = {
    'Lorde': ('神婆', '洛奶'), 'Katy Perry': ('水果姐',), 'Taylor Swift': ('霉霉',),
    'Olivia Rodrigo': ('娅娅',), 'Shakira': ('狼姐',), 'Dua Lipa': ('啪姐',),
    'Eminem': ('姆爷',), 'Adele': ('阿呆',), 'Sabrina Carpenter': ('匠妹',),
    'Lady Gaga': ('嘎嘎',), 'Ed Sheeran': ('黄老板',), 'Justin Timberlake': ('贾老板',),
    'Bruno Mars': ('火星哥',), 'Rihanna': ('日日',), 'John Legend': ('传奇哥',),
    'The Weeknd': ('盆栽哥',), 'Billie Eilish': ('碧梨',), 'Sam Smith': ('骚姆',),
    'Harry Styles': ('哈卷',), 'One Direction': ('小破团',), 'Beyoncé': ('Bee姐',),
    'Kendrick Lamar': ('喇嘛',), 'Imagine Dragons': ('梦龙',), 'Justin Bieber': ('B宝',),
}

def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))

def artist_nicknames(credit, curated=None):
    names = [curated] if isinstance(curated, str) else list(curated or [])
    normalized = normalize(credit or '')
    matches = []
    for artist, aliases in NICKNAMES.items():
        match = re.search(r'(?<![a-z0-9])' + re.escape(normalize(artist)) + r'(?![a-z0-9])', normalized)
        if match:
            matches.append((match.start(), aliases))
    for _, aliases in sorted(matches):
        names.extend(aliases)
    return list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
