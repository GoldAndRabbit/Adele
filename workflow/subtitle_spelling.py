"""Display spelling for English sung words. ASR evidence stays verbatim."""
import re

# Use known elided words so a closing quotation after e.g. 'again' stays intact.
_STEMS = set("""
goin comin drinkin somethin lookin sayin swervin fallin darlin wishin trippin
trashin nothin thinkin grindin rubbin grainin fuckin lovin doin wavin losin
livin havin everythin collectin holdin pourin feelin flashin singin servin
surfin talkin reppin mornin sleepin shootin pickin eatin movin rainin
runnin walkin waitin dancin drivin playin workin cryin tryin stayin hangin
laughin makin takin gettin givin sittin standin rockin rollin callin
""".split())
_ELIDED = re.compile(r"\b(" + "|".join(sorted(_STEMS)) + r")['’](?![a-z])", re.I)
_ACRONYMS = {"DJ", "TV", "VIP", "DNA", "USA", "UK", "LA", "NYC", "LGBT", "LGBTQ", "LGBTQIA", "APT"}


def sentence_case(text):
    """Remove caption-source all caps while retaining abbreviations and pronoun I."""
    words = re.findall(r"[^\W\d_]+", text)
    if not text.isupper() or not any(len(w) > 1 and w not in _ACRONYMS for w in words):
        return text
    # Chinese translations, annotation text and ASS commands have separate styles.
    if re.search(r"[\u3400-\u9fff{}]", text):
        return text
    text = re.sub(r"[^\W\d_]+", lambda m: m[0] if m[0] in _ACRONYMS else m[0].lower(), text)
    text = re.sub(r"\bi\b", "I", text)
    return re.sub(r"(^[\s\"'‘’“”(\[♪♫]*|[.!?]\s+)([^\W\d_])",
                  lambda m: m[1] + m[2].upper(), text)


def display_english(text):
    text = sentence_case(text)
    return _ELIDED.sub(lambda m: m[1] + ("G" if m[1].isupper() else "g"), text)
