"""Render the same deterministic scene to a portrait MP4 with aligned audio."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    parser.add_argument('--output', type=Path, default=BASE/'exports/aligned-preview.mp4')
    parser.add_argument('--width', type=int, default=1080, choices=[720, 1080])
    parser.add_argument('--fps', type=int, default=30, choices=[30, 60])
    args = parser.parse_args()
    data = json.loads((BASE/'preview/alignment.json').read_text())
    audio = BASE/'preview/aligned-audio.m4a'
    if not audio.is_file():
        parser.error('Run prepare.py first')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=BASE) as temp, sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.browser, headless=True)
        page = browser.new_page(viewport={'width': args.width, 'height': args.width*16//9})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto((BASE/'preview/scene-aligned.html').as_uri())
        page.add_style_tag(content=f'html {{zoom:{args.width/1080};}}')
        page.evaluate('document.fonts.ready')
        movie = Path(temp)/'video.mp4'
        command = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-framerate', str(args.fps), '-i', '-', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', str(movie)]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        try:
            for frame in range(round(data['duration']*args.fps)):
                page.evaluate('(t)=>drawAt(t)', frame/args.fps)
                encoder.stdin.write(page.screenshot(type='jpeg', quality=95))
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise RuntimeError('Video encoder failed')
            if errors:
                raise RuntimeError(errors)
        finally:
            if encoder.poll() is None:
                encoder.kill(); encoder.wait()
            browser.close()
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(movie), '-i', str(audio), '-map', '0:v', '-map', '1:a', '-c', 'copy', '-shortest', '-movflags', '+faststart', str(args.output)], check=True)
    print(args.output)

if __name__ == '__main__':
    main()
