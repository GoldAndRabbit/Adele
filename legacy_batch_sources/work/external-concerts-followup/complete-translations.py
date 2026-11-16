from run import *
from workflow.song import song_translation_workflow as W
from workflow.song.watermark import ensure_song
from workflow.live.refine import sub_title
import acoustic

def one(slug,name):
    checkpoint();load_env()
    from llm import PROVIDERS
    provider=os.environ.get("REPAIR_PROVIDER","aliyun")
    os.environ["LLM_PROVIDER"]=provider
    os.environ["OPENAI_BASE_URL"]=PROVIDERS[provider][0]
    W.MODEL="qwen-plus" if provider=="aliyun" else "deepseek-ai/DeepSeek-V3.2"; W.POETIC_MODEL=W.MODEL
    c=Concert(slug);it=c.item(name);d=c.song_dir(it);o=d/'subs'
    if not (o/'lyrics_poetic.ass').exists():
        W.translate(d,o,[t for t,_ in acoustic.section_lines(d/'lyrics.txt')],sub_title(c,it))
    ensure_song(slug,name)
    sub=subtitle_audit(c,it);meta=prepare_metadata(c,it)
    if sub["issues"] or meta["issues"]:raise ValueError(str(sub["issues"]+meta["issues"]))
    with (c.dir/'.publish-preview.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=c.load('setlist')
        next(r for r in data['items'] if r['name']==name)['review_hidden']=False
        write_json(c.setlist,data)
        path=BASE/slug/'results.json';results=read_json(path)
        row=next(r for r in results if r['song']==name);row.update(status='pending_human_review');row.pop('error',None);write_json(path,results)
    print("READY",slug,name,flush=True)

def worker(row):
    slug=row["concert"];name=row["link"].split('/')[-1]
    with (BASE/slug/(name+'.completion.log')).open('a') as log:
        code=subprocess.call([str(VENV_PY),'-u',__file__,slug,name],stdout=log,stderr=subprocess.STDOUT)
    print(slug,name,code,flush=True)

if __name__=="__main__":
    if len(sys.argv)>1:one(*sys.argv[1:])
    else:
        with (BASE/'complete-translations.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            jobs=[r for r in read_json(BASE/'live-audit.json')['items'] if not r['ready']]
            with ThreadPoolExecutor(max_workers=5) as pool:list(pool.map(worker,jobs))
