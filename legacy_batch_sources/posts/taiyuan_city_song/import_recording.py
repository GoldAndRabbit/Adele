"""Register a downloaded Suno recording in the local Taiyuan workbench."""
import argparse,json,shutil
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("file",type=Path)
p.add_argument("--song-id",required=True)
p.add_argument("--title",required=True)
p.add_argument("--draft",default="")
p.add_argument("--metadata",required=True,type=Path)
a=p.parse_args()
root=Path("/Users/gold/.codex/visualizations/2026/11/04/01a1a53c-553d-7a60-bb22-c5e7c5f7f7da/angel-local/dist")
if not a.file.is_file() or a.file.suffix.lower() not in [".mp3",".m4a",".wav"]:raise SystemExit("Expected a downloaded audio file")
if not all(c.isalnum() or c=="-" for c in a.song_id):raise SystemExit("Invalid song ID")
dest="audio/"+a.song_id+a.file.suffix.lower()
shutil.copy2(a.file,root/dest)
p=root/"recordings.json"
rows=json.loads(p.read_text())
url="https://suno.com/song/"+a.song_id
rows=[r for r in rows if r["url"]!=url]
rows.insert(0,dict(title=a.title,src=dest,url=url,group="原创完整歌曲",draft=a.draft,generation=json.loads(a.metadata.read_text())))
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(dest)

# Build once after import; UI stays static for recordings without reliable timestamps.
import subprocess
python=Path(__file__).resolve().parents[2]/".venv/bin/python"
for script in ["transcribe_timings.py","align_recordings.py"]:
    subprocess.run([str(python),str(Path(__file__).parent/script)],check=True)
