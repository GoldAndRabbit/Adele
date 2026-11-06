"""Optional external storage; existing project paths remain usable through links."""
import json
import os
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def external_root():
    config = ROOT / 'external_storage.json'
    if not config.exists():
        return None
    data = json.loads(config.read_text())
    if not data.get('enabled'):
        return None
    root = Path(data['root'])
    volume = root.parent
    if not volume.is_mount() or not root.is_dir():
        raise RuntimeError(f'外接工作盘未挂载：{volume}')
    expected = data.get('volume_uuid')
    if expected:
        info = plistlib.loads(subprocess.check_output(
            ['diskutil', 'info', '-plist', str(volume)], timeout=10))
        if info.get('VolumeUUID', '').upper() != expected.upper():
            raise RuntimeError(f'归档盘 UUID 不匹配：{volume}')
    if os.statvfs(root).f_flag & os.ST_RDONLY:
        raise RuntimeError(f'外接工作盘只读：{volume}')
    return root


def archive_root():
    root = external_root()
    if root is None:
        raise RuntimeError('未配置归档盘')
    return root


def prepare_song_directory(path):
    """New songs use external storage when configured; existing songs stay in place."""
    path = Path(path)
    if path.exists():
        return path
    if path.is_symlink():
        raise RuntimeError(f'歌曲存储链接不可用，请先连接工作盘：{path}')
    if path.parent != ROOT / 'posts':
        return path
    config = ROOT / 'external_storage.json'
    if config.exists() and json.loads(config.read_text()).get('processing') == 'local':
        return path
    root = external_root()
    if root is not None:
        target = root / 'posts' / path.name
        target.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target, target_is_directory=True)
    return path
