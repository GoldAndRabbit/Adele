"""Source acquisition adapter for the standard workflow; no rendering queue."""
import json
import shutil
import subprocess
from workflow.paths import ROOT
from workflow.youtube_download import cli_args
from workflow.storage import external_root
VENV_BIN = ROOT / '.venv/bin'

def run(cmd, cwd=None):
    print("\n$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd)

def tool(name):
    """优先使用 .venv 里的命令（yt-dlp）。"""
    p = VENV_BIN / name
    return str(p) if p.exists() else name

def stage_download(a, w):
    src = w / "source.mp4"
    if src.exists():
        print(f"已存在 {src}，跳过下载")
        return
    root = external_root()
    source_dir = root / "sources" / w.relative_to(ROOT) if root else w
    source_dir.mkdir(parents=True, exist_ok=True)
    session = cli_args(a.url, proxy=getattr(a, "proxy", None), browser=a.cookies_from_browser, cookie_file=a.cookies)
    # 下载参数和 SubDub（../SubDub/subdub/pipeline.py stage_download）保持一致
    cmd = [tool("yt-dlp"), "--no-playlist",
           # 画质最高到 2160p（这里和 SubDub 不同，SubDub 只要 1080p）；很多视频带 YouTube 自动配音的多语种音轨，
           # bestaudio 可能选到德语 / 印地语，只要原声
           # HDR 视频（观众拍的 4K HDR 常见）同时有 SDR 版本：优先要 SDR，不然后面转 H.264 8 位、不做色调映射，画面发灰
           "-f", "bv*[height<=2160][dynamic_range=SDR]+ba[format_note*=original]/bv*[height<=2160][dynamic_range=SDR]+ba[language^=en]/"
                 "bv*[height<=2160][dynamic_range=SDR]+ba/"
                 "bv*[height<=2160]+ba[format_note*=original]/bv*[height<=2160]+ba[language^=en]/bv*+ba/b",
           *session,
           "--merge-output-format", "mp4", "--retries", "10", "--fragment-retries", "10",
           *([] if getattr(a, 'no_source_subs', False) else
             ["--write-subs", "--sub-langs", "all,-live_chat,-danmaku", "--convert-subs", "srt"]),
           "--remux-video", "mp4", "-o", str(source_dir / "source.%(ext)s"),
           "-o", "subtitle:" + str(w / "source.%(ext)s")]
    if shutil.which("aria2c"):   # YouTube 单连接常被限速到几百 KB/s；aria2c 16 路并发快好几倍
        try:
            run(cmd + ["--downloader", "aria2c", "--downloader-args", "aria2c:-x 16 -s 16 -k 1M", a.url])
        except subprocess.CalledProcessError:   # aria2c 偶尔整个文件失败退出（Stan RRHOF 的音轨）：换 yt-dlp 自己的下载器再来一次
            print("aria2c 下载失败，改用 yt-dlp 自带下载器重试", flush=True)
            run(cmd + [a.url])
    else:
        run(cmd + [a.url])
    if root:
        target = source_dir / "source.mp4"
        result = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
            "-of", "json", str(target)
        ]))
        if not {"audio", "video"} <= {stream["codec_type"] for stream in result["streams"]} or float(result["format"]["duration"]) <= 0:
            raise RuntimeError(f"原视频音视频轨或时长不完整：{target}")
        if external_root() != root:
            raise RuntimeError("下载过程中归档盘已更换")
        src.symlink_to(target)
    # 保存元信息，后面标题行会用到
    info = subprocess.run([tool("yt-dlp"), *session, "--no-playlist", "--skip-download", "-J", a.url],
                          capture_output=True, text=True)
    if info.returncode == 0:
        d = json.loads(info.stdout)
        keep = {k: d.get(k) for k in ("title", "channel", "duration", "language", "track", "artist",
                                    "upload_date", "description", "tags", "webpage_url")}
        (w / "meta.json").write_text(json.dumps(keep, ensure_ascii=False, indent=2))
