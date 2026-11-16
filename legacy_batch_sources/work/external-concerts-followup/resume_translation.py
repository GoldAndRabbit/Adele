from run import *
import acoustic
from workflow.live.refine import sub_title
from workflow.song.song_translation_workflow import translate
from workflow.song.watermark import ensure_song

c=Concert("olivia_glastonbury_2025")
for name in ("15_favorite_crime","16_deja_vu","18_all_american_bitch"):
    checkpoint()
    it=c.item(name);d=c.song_dir(it);out=d/"subs"
    if subtitle_audit(c,it)["status"]!="missing":continue
    try:
        translate(d,out,[s for s,_ in acoustic.section_lines(d/"lyrics.txt")],sub_title(c,it))
        ensure_song(c.slug,name)
        audit=subtitle_audit(c,it);meta=prepare_metadata(c,it)
        if audit["issues"] or meta["issues"]:raise ValueError(str(audit["issues"]+meta["issues"]))
        data=c.load("setlist")
        for r in data["items"]:
            if r["name"]==name:r["review_hidden"]=False
        write_json(c.setlist,data)
        print("READY",name,flush=True)
    except Exception:traceback.print_exc()
