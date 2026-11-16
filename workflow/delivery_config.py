"""One production default for local/SSH encoders, schedulers and review counts.

Jobs persist their selected platforms in policy.json before dispatch, so later
configuration changes cannot change the outputs halfway through a song.
Existing videos and posting documents are preserved when a platform is disabled.
"""
from workflow.live.paths import ROOT, read_json
from pathlib import Path

CONFIG = ROOT / 'delivery_defaults.json'
SUPPORTED = {'bilibili', 'douyin'}


def single_channel_pipeline():
    value = read_json(CONFIG, {}).get('single_channel_pipeline', 'master')
    if value not in ('master', 'stream'):
        raise ValueError('single_channel_pipeline 需为 master 或 stream')
    return value


def render_platforms(value=None):
    if value is None:
        value = read_json(CONFIG, {}).get('render_platforms', ['bilibili'])
    if (not isinstance(value, (list, tuple)) or not value
            or any(platform not in SUPPORTED for platform in value)
            or len(set(value)) != len(value)):
        raise ValueError('制作平台需为 bilibili/douyin 的非空列表，不能重复')
    return tuple(value)


def collection_platforms():
    value = read_json(CONFIG, {}).get('collection_platforms', ['bilibili'])
    if not isinstance(value, list) or any(platform not in SUPPORTED for platform in value):
        raise ValueError('合集平台需为 bilibili/douyin 列表')
    return tuple(value)


def products_ready(directory, platforms=None):
    """Only required platforms count; actual nonempty files must exist."""
    directory = Path(directory)
    current_check = None
    check = directory / 'reports/content_check.json'
    from workflow.content_check import audit_enabled
    if check.is_file() and audit_enabled():
        from workflow.content_check import require_directory, ContentCheckFailed
        try:
            current_check = require_directory(directory)
        except (ContentCheckFailed, OSError, ValueError, KeyError):
            return False
    products = directory / 'products'
    manifest = read_json(products / 'products.json', {})
    if current_check and (manifest.get('source_policy', {}).get('content_check', {}).get('fingerprint')
                          != current_check['fingerprint']):
        return False
    ready = {row.get('platform') for row in manifest.get('items', [])
             if row.get('status') == 'ready' and row.get('file')
             and (products / row['file']).is_file()
             and (products / row['file']).stat().st_size > 0}
    return manifest.get('status') == 'ready' and set(render_platforms(platforms)) <= ready
