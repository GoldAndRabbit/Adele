"""Recover missing performances from the source transcript, then rerun the existing preview workflow."""
import concurrent.futures
import fcntl
from run import *

import threading
import run as producer
audio_slots=threading.BoundedSemaphore(2)
def limited_audio(concert,item):
    with audio_slots:
        return ensure_audio(concert,item)
producer.ensure_audio=limited_audio

def extend(job):
    folder=BASE/job["slug"]
    rows=read_json(folder/"transcript.json")
    spans=read_json(folder/"locations.json")
    found={s["idx"] for s in spans}
    for idx,entry in enumerate(job["catalog"],1):
        if idx in found:continue
        checkpoint()
        before=max((s for s in spans if s["idx"]<idx),key=lambda s:s["idx"],default={})
        after=min((s for s in spans if s["idx"]>idx),key=lambda s:s["idx"],default={})
        start=before.get("end",0);end=after.get("start",rows[-1]["end"])
        window=[r for r in rows if r["t"]>=start and r["t"]<end]
        if not window:continue
        request={"performance":entry,"transcript":window}
        proof=folder/f"verified-location-{idx}.json"
        hit=read_json(proof,{})
        if not hit:
            hit=chat_json("输出 JSON。核对给定时段是否确有目标曲目连续现场演唱。仅有介绍、标题、提名或背景片段不算。找到时返回 first,last（包括整段演出的起末20秒行的t）, artist_zh, anchors（2个分别取自不同演唱行的对象，每个含 t 和原样摘录连续至少三个词的 text）。找不到返回空对象。不能以相邻曲目之间的空隙直接推定演唱。",json.dumps(request,ensure_ascii=False),label="缺项原片复核")
        if not hit:continue
        source={r["t"]:r for r in window}
        a,b=hit.get("first"),hit.get("last")
        if a not in source or b not in source or b-a<20:continue
        matches={h["t"] for h in hit.get("anchors",[]) if h.get("t") in source and a<=h["t"]<=b and len(norm(h.get("text","")).split())>=3 and norm(h["text"]) in norm(source[h["t"]]["text"])}
        if len(matches)<2:continue
        spans.append(dict(idx=idx,start=a,end=min(end,source[b]["end"]),artist_zh=hit.get("artist_zh") or job["artist_zh"]))
        write_json(proof,hit)
        write_json(folder/"locations.json",sorted(spans,key=lambda s:s["start"]))
    return spans

def repair(job):
    folder=BASE/job["slug"]
    try:
        extend(job)
        result=produce(job)
    except Exception as exc:
        traceback.print_exc()
        result={"error":str(exc)}
    write_json(folder/"repair-summary.json",result)
    print(job["slug"],result,flush=True)

if __name__=="__main__":
    load_env()
    with (BASE/"repair.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Disjoint shows can run concurrently. Wait for the primary worker to release each show.
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[]
            for job in QUEUE:
                while job["slug"] not in read_json(BASE/"results.json",{}):
                    checkpoint();time.sleep(20)
                futures.append(pool.submit(repair,job))
            for f in futures:f.result()
