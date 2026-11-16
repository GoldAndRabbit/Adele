"""Inventory evidence for this batch, including songs missing from generated setlists."""
from run import *
from datetime import datetime
import pysubs2
def audit_job(slug,catalog):
    c=Concert(slug);items={r['idx']:r for r in c.song_items()} if c.setlist.exists() else {}
    records=[]
    for idx,entry in enumerate(catalog,1):
        it=items.get(idx)
        row=dict(concert=slug,idx=idx,title=entry.get("title"),ready=False)
        if it:
            d=c.song_dir(it);clip=d/'vertical/original-selected.mp4'
            sub=subtitle_audit(c,it);bundle=read_json(d/'delivery_bundle.json',{}) or {}
            song=read_json(d/'song.json',{}) or {}
            if clip.is_file() and song.get("slice"):
                duration=float(probe(clip)["format"]["duration"])
                row["clip_verified"]=abs(duration-(song["slice"][1]-song["slice"][0]))<.3
            if sub.get("file"):
                events=pysubs2.load(sub["file"])
                row["bilingual_cues"]=sum(1 for e in events if not e.is_comment and e.style!='Note' and "takit.app" not in e.plaintext and len(e.plaintext.splitlines())>=2 and re.search(r"[a-zA-Záéíóúñ]",e.plaintext) and re.search(r"[\u3400-\u9fff]",e.plaintext))
            row.update(subtitles=sub.get('status'),metadata=bool(bundle.get('bilibili') and bundle.get('douyin')),visible=not it.get('review_hidden',False))
            row["ready"]=bool(row.get("clip_verified") and row["metadata"] and row["visible"] and sub["status"]=="structurally_valid" and row.get("bilingual_cues",0)>0)
            row["link"]=f"http://127.0.0.1:8160/#/{slug}/{it['name']}"
        records.append(row)
    return records
if __name__=='__main__':
    out=[]
    for job in QUEUE:
        rows=audit_job(job['slug'],job['catalog']);out+=rows
        print(job['slug'],sum(x['ready'] for x in rows),len(rows),flush=True)
    write_json(BASE/'preview-audit.json',dict(updated=datetime.now().isoformat(),ready=sum(x['ready'] for x in out),total=len(out),items=out))
