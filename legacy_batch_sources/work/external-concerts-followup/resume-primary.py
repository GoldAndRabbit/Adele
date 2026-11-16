from run import *
load_env()
for pid in map(int,sys.argv[1:]):
    while True:
        try:os.kill(pid,0)
        except ProcessLookupError:break
        time.sleep(3)
with (BASE/'runner.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finished=read_json(BASE/'results.json',{})
    for job in QUEUE:
        if job['slug'] in finished:continue
        checkpoint()
        write_json(BASE/'state.json',dict(status="running",current=job["slug"],pid=os.getpid(),results=finished))
        try:finished[job['slug']]=produce(job)
        except Exception as exc:
            traceback.print_exc()
            finished[job['slug']]=dict(error=str(exc))
        write_json(BASE/'results.json',finished)
    write_json(BASE/'state.json',dict(status='reconciling_repaired_previews',results=finished))
