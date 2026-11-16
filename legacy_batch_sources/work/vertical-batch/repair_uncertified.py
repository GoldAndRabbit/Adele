"""Recheck existing whole-song outputs after batch changes; respect selections and previous receipts."""
import fcntl
from pathlib import Path
from workflow.live.paths import ROOT,CONCERTS,Concert,read_json
from workflow.portrait_validation import preview_problem
from workflow.vertical_preview import render
from workflow.vertical_workflow import revision,release

base=Path(__file__).resolve().parent
with (base/'queue.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    for p in sorted(CONCERTS.iterdir()):
        if not p.is_dir():continue
        c=Concert(p.name)
        for item in c.song_items():
            if (base/'PAUSED').exists():raise SystemExit('Paused')
            if item.get('review_hidden'):continue
            directory=c.song_dir(item)
            folder=directory/'vertical'
            video=folder/'full.mp4'
            if not video.is_file() or not preview_problem(c,item,video):continue
            try:
                render(c,item,True,full=True)
                assert not preview_problem(c,item,video)
                prior=read_json(folder/'release.json',{})
                choice=read_json(folder/'selected.json',{}).get('cover')
                if prior.get('file') and choice==prior.get('cover'):
                    release(directory,choice,revision(directory),prior['lead'],concert=c,item=item)
                print('REPAIRED',c.slug,item['name'],flush=True)
            except Exception as error:
                print('FAIL',c.slug,item['name'],str(error),flush=True)
