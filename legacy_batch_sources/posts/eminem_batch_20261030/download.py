"""本次下载使用 yt-dlp 原生下载器，避免 aria2 在该网络上连接挂起。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'workflow'))
import make_mv
original_which = make_mv.shutil.which
make_mv.shutil.which = lambda name: None if name == 'aria2c' else original_which(name)
make_mv.main()
