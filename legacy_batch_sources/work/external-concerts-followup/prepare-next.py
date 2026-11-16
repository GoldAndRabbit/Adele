from run import *
load_env()
for job in QUEUE[-2:]:
    checkpoint()
    folder=BASE/job['slug'];folder.mkdir(exist_ok=True)
    if (folder/'locations.json').exists():continue
    staging=DATA/'work'/'external-concert-preview'/job['slug']
    staging.mkdir(parents=True,exist_ok=True)
    duration=float(probe(job['source'])['format']['duration'])
    rows=transcript(job,duration,staging)
    spans=locate(job,rows,staging)
    for name in ['transcript.json', 'locations.json']:
        # Publish fully parsed files only when the existing runner has not produced one.
        temp=folder/(name+'.prepared')
        temp.write_bytes((staging/name).read_bytes())
        try:os.link(temp,folder/name)
        except FileExistsError:pass
        finally:temp.unlink()
    print(job['slug'],len(spans),'located',flush=True)
