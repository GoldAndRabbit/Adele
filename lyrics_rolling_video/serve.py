"""Serve only the preview directory on loopback; never expose the repository or credentials."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    subprocess.run([sys.executable, str(BASE/'build.py')], check=True)
    if not (BASE/'preview/aligned-audio.m4a').is_file():
        parser.error('Preview audio missing; run prepare.py with the project .venv first. See README.md.')
    handler = partial(Handler, directory=str(BASE/'preview'))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError as exc:
        parser.exit(1, f'无法使用端口 {args.port}：{exc}\n可换端口：python3 {BASE.name}/serve.py --port 8766\n')
    print(f'歌词预览：http://127.0.0.1:{server.server_port}/\n保持此窗口运行；Ctrl+C 停止服务。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
