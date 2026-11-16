from repair import *
load_env()
for job in QUEUE[2:]:
    folder=BASE/job["slug"]
    while not (folder/"locations.json").is_file():
        checkpoint();time.sleep(30)
    spans=extend(job)
    print(job["slug"],len(spans),"/",len(job["catalog"]),flush=True)
