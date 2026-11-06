"""Shared yt-dlp setup for source downloads, retries and metadata lookups.

The local service supplies per-video PO Tokens to yt-dlp. Callers supply a URL,
not a token, and keep their own format, destination and retry policy.
"""

import json
import os
import shutil
import subprocess
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
PROVIDER = "http://127.0.0.1:4416"
CLIENTS = ("default", "mweb")


def _healthy(expected):
    # The video request may use a proxy. The health check must stay on loopback.
    try:
        with build_opener(ProxyHandler({})).open(PROVIDER + "/ping", timeout=0.6) as response:
            info = json.loads(response.read(4096))
    except (OSError, ValueError):
        return False
    if not isinstance(info, dict) or "server_uptime" not in info:
        raise RuntimeError("4416 端口的响应不是 bgutil 服务。")
    if info.get("version") != expected:
        raise RuntimeError(f"bgutil 服务版本与插件 {expected} 不一致，请检查 4416 端口。")
    return True


def ensure_provider():
    """Reuse a healthy service or start the installed matching server on demand."""
    try:
        expected = version("bgutil-ytdlp-pot-provider")
    except PackageNotFoundError as exc:
        raise RuntimeError("请用项目 .venv 并安装 requirements.txt 中的 bgutil 插件。") from exc
    if _healthy(expected):
        return

    # flock is released on exit/crash; concurrent download workers share one server.
    import fcntl
    cache = Path.home() / ".cache" / "adele"
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "bgutil-start.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _healthy(expected):
            return
        default = ROOT.parent / "SubDub/tools/bgutil-pot/server"
        server = Path(os.environ.get("ADELE_BGUTIL_SERVER_DIR", default)).expanduser().resolve()
        entry = server / "build/main.js"
        node = shutil.which("node")
        if not node or not entry.is_file():
            raise RuntimeError(f"无法启动 PO Token 服务：需要 Node 和已编译的 {entry}。")
        # Never launch an unauthenticated provider on the LAN or log token values.
        child = subprocess.Popen([node, str(entry), "--host", "127.0.0.1", "--port", "4416"],
                                 cwd=server, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        try:
            for _ in range(50):
                if _healthy(expected):
                    return
                if child.poll() is not None:
                    raise RuntimeError("bgutil 启动失败，请检查 Node 版本和 4416 端口。")
                time.sleep(0.2)
            raise RuntimeError("bgutil 健康检查超时。")
        except BaseException:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=3)
            raise


def extractor_options(url):
    """Return the same extractor settings for yt-dlp's Python and CLI clients."""
    host = (urlsplit(url).hostname or "").lower()
    if not any(host == domain or host.endswith("." + domain)
               for domain in ("youtube.com", "youtube-nocookie.com", "youtu.be")):
        return {}
    ensure_provider()
    return {"youtube": {"player_client": list(CLIENTS)},
            "youtubepot-bgutilhttp": {"base_url": [PROVIDER]}}


def cli_args(url, *, proxy=None, browser=None, cookie_file=None):
    """Build session arguments once; reuse them for media, retries and metadata."""
    args = []
    for extractor, settings in extractor_options(url).items():
        spec = ";".join(f"{key}={','.join(values)}" for key, values in settings.items())
        args.extend(["--extractor-args", f"{extractor}:{spec}"])
    if proxy is not None:  # Empty string explicitly selects a direct connection.
        args.extend(["--proxy", proxy])
    if browser:
        args.extend(["--cookies-from-browser", browser])
    if cookie_file:
        args.extend(["--cookies", cookie_file])
    return args
