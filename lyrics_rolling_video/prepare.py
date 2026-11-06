"""Prepare an audio excerpt, force-align checked lyrics, then rebuild the local UI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent

def run(*args):
    subprocess.run([str(x) for x in args], check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Existing full-length audio/video; start time is read from config.json')
    parser.add_argument('--download', action='store_true', help='Download config.json source_url with yt-dlp')
    parser.add_argument('--cookies-from-browser', help='Explicitly opt into browser login access, e.g. chrome')
    args = parser.parse_args()
    if args.download and args.source:
        parser.error('Choose --source or --download, not both')
    if args.cookies_from_browser and not args.download:
        parser.error('--cookies-from-browser requires --download')
    config = json.loads((BASE/'config.json').read_text())
    if config['source_start'] < 0 or config['duration'] <= 0:
        parser.error('Invalid audio interval in config.json')
    data = BASE/'data'; data.mkdir(exist_ok=True)
    preview = BASE/'preview'; preview.mkdir(exist_ok=True)
    source = args.source.resolve() if args.source else data/'source.webm'
    if args.download:
        command = [sys.executable, '-m', 'yt_dlp', '--no-playlist', '--socket-timeout', '20', '--retries', '2', '-f', 'bestaudio/best', '-o', str(data/'source.%(ext)s'), '--print', 'after_move:filepath']
        if args.cookies_from_browser:
            command += ['--cookies-from-browser', args.cookies_from_browser]
        result = subprocess.run(command+[config['source_url']], check=True, capture_output=True, text=True)
        # Only expose the downloaded path; do not retain cookie material or metadata headers.
        source = Path(result.stdout.strip().splitlines()[-1])
    if not source.is_file():
        parser.error('Source missing: use --source /path/to/audio or --download')
    common = ['ffmpeg', '-y', '-loglevel', 'error', '-ss', str(config['source_start']), '-i', source, '-t', str(config['duration']), '-vn']
    run(*common, '-ac', '1', '-ar', '16000', data/'align.wav')
    run(*common, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', preview/'aligned-audio.m4a')
    run(sys.executable, BASE/'align.py')
    run(sys.executable, BASE/'build.py')

if __name__ == '__main__':
    main()
