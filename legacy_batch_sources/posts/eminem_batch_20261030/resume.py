import os,time
children=[64963]
for pid in children:
    while True:
        try: os.kill(pid,0)
        except ProcessLookupError: break
        time.sleep(2)
os.execv('/Users/gold/repos/adele/.venv/bin/python', ['python','-u','/Users/gold/repos/adele/posts/eminem_batch_20261030/run.py','--remaining-only'])
