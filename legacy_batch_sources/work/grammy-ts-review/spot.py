exec(open('work/grammy-ts-review/qwen.py').read().split('with ThreadPoolExecutor')[0])
tasks=[('pink-verse',3417,35),('one-firstsong',7370,35),('one-j1',7450,15),('one-j2',7580,10),('invisible-fast',1251,18)]
with ThreadPoolExecutor(max_workers=3) as ex:list(ex.map(job,tasks))
