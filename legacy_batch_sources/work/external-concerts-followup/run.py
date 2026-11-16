"""Produce the remaining external concert previews after the Grammy 2025/26 audit."""
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "workflow")]
os.chdir(ROOT)

import numpy as np
import requests
from openai import OpenAI
from rapidfuzz import fuzz
from llm import chat_json, load_env
from qwen_asr import transcribe, ENDPOINT, SR
from workflow.browser_library import probe
from workflow.live.lyrics import guess_lang
from workflow.live.paths import Concert, POSTS, VENV_PY, read_json, write_json, slugify
from workflow.live.segment import norm
from workflow.subtitle_metadata_batch import ensure_audio, prepare_metadata, subtitle_audit

PREVIOUS = ROOT / "work/grammys-2025-2026"
DATA = Path("/Volumes/harddisk_5T/adele-workflow")
QUEUE = read_json(BASE / "queue.json")


def checkpoint():
    while any(p.exists() for p in (BASE / "PAUSED", ROOT / "work/subtitle-metadata-library/PAUSED")):
        time.sleep(30)


def transcript(job, duration, folder):
    """Time each recognition window against decoded audio, including elapsed silence."""
    target = folder / "transcript.json"
    if target.exists():
        return read_json(target)
    pcm = folder / "mono16.pcm"
    if not pcm.exists():
        temporary = pcm.with_suffix(".partial")
        subprocess.run(["/opt/homebrew/bin/ffmpeg", "-nostdin", "-v", "error", "-y",
                        "-i", job["source"], "-map", "0:a:0", "-ar", str(SR),
                        "-ac", "1", "-af", "aresample=async=1:first_pts=0", "-f", "s16le", str(temporary)], check=True)
        temporary.replace(pcm)
    samples = np.memmap(pcm, dtype="<i2", mode="r")
    if abs(len(samples) / SR - duration) > 6:
        raise ValueError(f"Decoded audio and video durations differ: {len(samples)/SR} vs {duration}")
    client = OpenAI(base_url=ENDPOINT, api_key=os.environ["ALIYUN_BAILIAN_API_KEY"])
    cache = folder / "asr-chunks"
    cache.mkdir(exist_ok=True)
    def one(start):
        checkpoint()
        record = cache / f"{start}.json"
        if record.exists():
            return read_json(record)
        audio = samples[start*SR:(start+20)*SR].astype(np.float32) / 32768
        words = transcribe(client, audio, None)
        if words is None:
            raise RuntimeError(f"ASR failed at {start}s")
        row = dict(t=start, end=min(start+20,duration), text=words.strip())
        write_json(record,row)
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(one,range(0,int(np.ceil(len(samples)/SR)),20)))
    write_json(target,rows)
    return rows


def locate(job, rows, folder):
    target = folder / "locations.json"
    if target.exists():
        return read_json(target)
    # Provide a bounded part of the transcript per call, retaining a full performance across adjacent windows.
    evidence = {}
    for first in range(0,len(rows),60):
        checkpoint()
        chunk = rows[max(0,first-4):first+64]
        cache = folder / f"locations-{first}.json"
        if not cache.exists():
            inp = {"节目":job["event"], "目录":list(enumerate(job["catalog"],1)), "原片带时间的识别":chunk}
            result = chat_json("请根据实际连续演唱的歌词和介绍，将转播原片中的演出对应到给定目录序号。"
                "不要将提名、颁奖、报歌名、短宣传、背景回放当作演出。仅返回有演唱证据的目录项。"
                "每项返回 idx, artist_zh（演唱者中文常用署名，多人以 & 连接，无通用译名时保留原名）, "
                "first 和 last（本窗口中确认属于演出的首末20秒行的 t），"
                "anchor（直接摘录该演唱识别中的连续几个词供程序验证）。仅输出 JSON {items:[...]}。"
                "不确定就省略，不要猜测时间、曲名或填补未唱的段落。",json.dumps(inp,ensure_ascii=False),label="演出定位")
            write_json(cache,result)
        for row in read_json(cache).get("items",[]):
            idx=int(row["idx"]);a=float(row["first"]);b=float(row["last"])
            selected=[s for s in chunk if a<=s["t"]<=b]
            anchor=norm(str(row.get("anchor","")))
            if not 1<=idx<=len(job["catalog"]) or not selected or len(anchor.split())<2:continue
            if a!=selected[0]["t"] or b!=selected[-1]["t"]:continue
            if anchor not in norm(" ".join(s["text"] for s in selected)):continue
            evidence.setdefault(idx,[]).append((a,selected[-1]["end"],str(row.get("artist_zh",""))))
    located=[]
    for idx,hits in sorted(evidence.items()):
        groups=[]
        for a,b,zh in sorted(hits):
            if not groups or a>groups[-1][1]+20: groups.append([a,b,zh])
            else:groups[-1][1]=max(b,groups[-1][1])
        a,b,zh=max(groups,key=lambda g:g[1]-g[0])
        if b-a>=40:located.append(dict(idx=idx,start=a,end=b,artist_zh=zh))
    located.sort(key=lambda s:s["start"])
    for previous,current in zip(located,located[1:]):
        if previous["end"]>current["start"]:
            mid=(current["start"]+previous["end"])/2
            previous["end"]=current["start"]=mid
    write_json(target,located)
    return located


def lyrics(it, folder):
    # Use the established Genius path or a matching published LRCLIB reference.
    from workflow.lyrics_library import genius_lookup
    from workflow.live.lyrics import fetch_part
    chunks=[]
    for part in it["parts"]:
        saved=genius_lookup(it["artist"],part)
        found=saved["plain"] if saved else None
        # Reuse text only. All timings and translations come from this performance.
        for candidate in sorted((ROOT / "concerts").glob("*/songs/*/lyrics.txt")):
            if found:break
            other = read_json(candidate.parent / "song.json", {}) or {}
            if candidate.parent != folder and norm(other.get("title") or "") == norm(part) and norm(other.get("artist") or "") == norm(it["artist"]):
                found = candidate.read_text().strip()
                if found:break
        for artist in ([] if found else it["artist"].split(" & ")):
            try:
                res=requests.get("https://lrclib.net/api/search",params={"track_name":part,"artist_name":artist},timeout=15)
                res.raise_for_status()
                found=next((r["plainLyrics"] for r in res.json() if norm(r["trackName"])==norm(part)
                            and norm(artist) in norm(r["artistName"]) and r.get("plainLyrics")),None)
            except requests.RequestException:pass
            if found:break
        if not found:
            with requests.Session() as session:
                try:
                    _,found,_,_=fetch_part(session,part,it["artist"].split(" & ")[0])
                except (requests.RequestException,ValueError):
                    found=None
        if not found or not found.strip():
            record=read_json(folder/"song.json")
            start,end=record["slice"]
            transcript=read_json(BASE/folder.parents[1].name/"transcript.json")
            lines=[row["text"].strip() for row in transcript if start<=row["t"]<end and row["text"].strip()]
            if not lines:raise ValueError("No audible source reference for "+part)
            references=[sentence.strip() for line in lines for sentence in re.split(r"(?<=[.!?。！？])\s+",line) if sentence.strip()]
            reference="\n".join(references)+"\n"
            for name in ("lyrics.txt","lyrics_sections.txt"):(folder/name).write_text(reference)
            (folder/"lyrics_source").write_text("source-asr; manual review required")
            return
        chunks.append(found.strip())
    reference="\n\n\n".join(chunks)+"\n"
    (folder/"lyrics.txt").write_text(reference)
    (folder/"lyrics_sections.txt").write_text(reference)
    (folder/"lyrics_source").write_text("reference")


def produce(job):
    source=Path(job["source"])
    if source.stat().st_size!=job["bytes"]:raise ValueError("Source file changed since inventory")
    c=Concert(job["slug"]);folder=BASE/c.slug;folder.mkdir(exist_ok=True)
    m=probe(source);v=next(s for s in m["streams"] if s["codec_type"]=="video");duration=float(m["format"]["duration"])
    rows=transcript(job,duration,folder);spans=locate(job,rows,folder)
    c.dir.mkdir(exist_ok=True);real=DATA/"posts"/c.slug;real.mkdir(parents=True,exist_ok=True)
    if not (POSTS/c.slug).exists():(POSTS/c.slug).symlink_to(real)
    info=dict(slug=c.slug,source_file=str(source),artist=job["artist"],artist_zh=job["artist_zh"],
              title=job["event"],title_zh=job["event"],title_en=job["event_en"],date=job["event"][:4],
              duration=duration,width=v["width"],height=v["height"],fps_str=v["r_frame_rate"],video_codec=v["codec_name"])
    write_json(c.info,info)
    old={i['name']:i for i in c.song_items()};items=[];segments=[];original_names=[]
    for sp in spans:
        idx=sp["idx"];entry=job["catalog"][idx-1];title=entry["title"];name=f"{idx:02d}_{slugify(title)}"
        zh=entry.get("artist_zh") or sp["artist_zh"] or entry["artist"]
        if entry["artist"]=="Fun" and zh.rstrip(".").casefold()=="fun":zh="欢娱乐队"
        if zh.casefold()==entry["artist"].casefold():original_names.append(entry["artist"])
        it=dict(idx=idx,name=name,title=title,artist=entry["artist"],artist_zh=zh,parts=title.split(" / "),
                notes="",kind="song",review_hidden=old.get(name,{}).get("review_hidden",True))
        items.append(it);segments.append(dict(idx=idx,name=name,title=title,kind="song",start=sp["start"],end=sp["end"],review="pending",flags=["原片ASR初定位，首尾待人工复核"]))
    write_json(c.setlist,dict(source=job["reference"],items=items))
    write_json(c.segments,dict(items=segments,gaps=[]))
    write_json(c.dir/"vertical_preview.json",dict(original_artist_names=original_names))
    results=[]
    previous_results={row["song"]:row for row in read_json(folder/"results.json",[])}
    for it,seg in zip(items,segments):
        checkpoint();d=c.make_song_dir(it)
        try:
            if not (d/"song.json").exists():write_json(d/"song.json",dict(it,source_file=str(source),slice=[seg["start"],seg["end"]]))
            if not (d/"post_draft.json").exists():write_json(d/"post_draft.json",dict(song={k:it[k] for k in ("title","artist","artist_zh")},performance=dict(event=info["title"],event_en=info["title_en"],date=info["date"]),intro={},tags=[]))
            if it["artist"]=="Fun":
                draft=read_json(d/"post_draft.json");draft["song"]["artist_zh"]=it["artist_zh"];write_json(d/"post_draft.json",draft)
            if not (d/"lyrics.txt").exists():lyrics(it,d)
            song=read_json(d/"song.json");song.setdefault("lang",guess_lang((d/"lyrics.txt").read_text()));write_json(d/"song.json",song)
            if subtitle_audit(c,it)["status"]=="missing":
                ensure_audio(c,it)
                with (folder/(it["name"]+".log")).open("a") as log:
                    subprocess.run([str(VENV_PY),"-u","-m","workflow.song.run","song",c.slug,it["name"]],stdout=log,stderr=subprocess.STDOUT,check=True)
            sub=subtitle_audit(c,it);meta=prepare_metadata(c,it)
            if sub["issues"] or meta["issues"]:raise ValueError(str(sub["issues"]+meta["issues"]))
            clip=d/"vertical/original-selected.mp4"
            if abs(float(probe(clip)["format"]["duration"])-(seg["end"]-seg["start"]))>.3:raise ValueError("Preview duration mismatch")
            it["review_hidden"]=False;write_json(c.setlist,dict(source=job["reference"],items=items))
            results.append(dict(song=it["name"],status="pending_human_review"))
        except Exception as exc:
            results.append(dict(song=it["name"],status="needs_repair",error=str(exc)));traceback.print_exc()
        previous_results[it["name"]]=results[-1]
        write_json(folder/"results.json",list(previous_results.values()))
    missing=sorted(set(range(1,len(job["catalog"])+1))-{s["idx"] for s in spans})
    return dict(catalog=len(job["catalog"]),located=len(spans),ready=sum(r["status"]=="pending_human_review" for r in results),unlocated_catalog_entries=missing)


def main():
    load_env()
    with (BASE/"runner.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write_json(BASE/"state.json",dict(status="waiting_for_grammys_2025_2026",pid=os.getpid(),queued=len(QUEUE)))
        while read_json(PREVIOUS/"finish-status.json",{}).get("ready_for_review")!=34:
            checkpoint();time.sleep(30)
        completed={}
        for job in QUEUE:
            checkpoint();write_json(BASE/"state.json",dict(status="running",current=job["slug"],results=completed,pid=os.getpid()))
            try:completed[job["slug"]]=produce(job)
            except Exception as exc:
                completed[job["slug"]]=dict(error=str(exc));traceback.print_exc()
            write_json(BASE/"results.json",completed)
        ready=all(v.get("ready",0)==len(j["catalog"]) for j in QUEUE for v in [completed[j["slug"]]])
        write_json(BASE/"state.json",dict(status="pending_human_review" if ready else "needs_source_or_track_review",results=completed))
if __name__=="__main__":main()
