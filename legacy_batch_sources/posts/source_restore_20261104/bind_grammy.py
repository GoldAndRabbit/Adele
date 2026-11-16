import os,hashlib,json,subprocess
from pathlib import Path
from workflow.storage import archive_root
p=Path('concerts/grammys_2014/source.mp4')
orig=p.resolve()
target=archive_root().parent/'thunder_downloads/VA - The 56th Grammy Awards [2014]/VA - The 56th Grammy Awards [2014].mkv'
def digest(path):
 with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
a=digest(orig);b=digest(target)
assert a==b and orig.stat().st_size==target.stat().st_size
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type:format=duration','-of','json',str(target)]))
assert {'audio','video'}<={s['codec_type'] for s in probe['streams']} and abs(float(probe['format']['duration'])-9872.544)<1
assert p.is_symlink() and p.resolve()==orig
tmp=p.with_name('.source.external');tmp.symlink_to(target);tmp.replace(p)
Path('posts/source_restore_20261104/grammy_verified.json').write_text(json.dumps(dict(target=str(target),sha256=a,probe=probe),ensure_ascii=False,indent=2))
