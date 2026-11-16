"""Maintain the review roster while this one batch is running."""
from run import *
from importlib.util import spec_from_file_location,module_from_spec
from datetime import datetime
spec=spec_from_file_location("preview_audit",BASE/"preview-audit.py")
audit=module_from_spec(spec);spec.loader.exec_module(audit)
previous=None
while True:
    checkpoint()
    snapshot=tuple((p.stat().st_mtime_ns,p) for j in QUEUE for p in (Concert(j['slug']).setlist,BASE/j['slug']/'results.json') if p.exists())
    if snapshot!=previous:
        rows=[r for j in QUEUE for r in audit.audit_job(j['slug'],j['catalog'])]
        write_json(BASE/'live-audit.json',dict(updated=datetime.now().isoformat(),ready=sum(r['ready'] for r in rows),total=len(rows),items=rows))
        previous=snapshot
    try:os.kill(int(sys.argv[1]),0)
    except ProcessLookupError:break
    time.sleep(45)
