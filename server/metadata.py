"""Cache parsed review metadata, invalidating it when the file changes.

The review workspace lives on an external disk. Reopening thousands of small
JSON files on every index refresh is much slower than checking their versions.
Callers receive independent objects because some response builders add fields.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=8192)
def _load(path, modified, size, inode):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_json(path, default=None):
    path = Path(path)
    try:
        version = path.stat()
    except FileNotFoundError:
        return default
    return deepcopy(_load(str(path), version.st_mtime_ns, version.st_size, version.st_ino))
