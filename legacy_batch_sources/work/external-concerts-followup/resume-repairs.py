import os, subprocess,time,sys
from pathlib import Path
folder=Path(__file__).resolve().parent
for pid in map(int,sys.argv[1:]):
    while True:
        try:os.kill(pid,0)
        except ProcessLookupError:break
        time.sleep(3)
os.execv(sys.executable,[sys.executable,'-u',str(folder/'repair.py')])
