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


def display_english(text):
    return _ELIDED.sub(lambda m: m[1] + ("G" if m[1].isupper() else "g"), text)
