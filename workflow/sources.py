"""Resolve one authoritative original and slice for every song-level module."""
from pathlib import Path

from workflow.live.paths import POSTS, read_json, write_json
from workflow.runtime import locked


def selection(concert, item):
    directory = concert.song_dir(item)
    policies = read_json(concert.dir / "vertical_source.json", {})
    explicit = policies.get("songs", {}).get(item["name"])
    if explicit:
        result = dict(explicit)
        result["source"] = result.get("source") or policies.get("source")
    else:
        song = read_json(directory / "song.json", {})
        info = concert.load("info") or {}
        source = str(original_source(concert, item))
        segment = next((row for row in (concert.load("segments") or {}).get("items", [])
                        if row["name"] == item["name"]), {})
        # A deliberate per-song slice wins over a legacy segmentation projection.
        span = song.get("slice") or ([segment["start"], segment["end"]]
                                     if segment.get("start") is not None else None)
        result = {"source": source, "slice": span}
    if not result.get("source") or not Path(result["source"]).is_file():
        raise FileNotFoundError("指定原片不可用，不自动回退其他版本")
    span = result.get("slice")
    if (not isinstance(span, (list, tuple)) or len(span) != 2
            or span[0] < 0 or span[1] <= span[0]):
        raise ValueError("缺少有效的已确认曲目范围")
    return result


def ensure_selection(concert, item):
    """Persist a missing adapter policy without overwriting an explicit choice."""
    with locked(concert.dir / ".source-policy.lock", blocking=True):
        data = read_json(concert.dir / "vertical_source.json", {"songs": {}})
        current = selection(concert, item)
        if item["name"] in data.get("songs", {}):
            return current
        info = concert.load("info") or {}
        current.update(kind="original", fps=info.get("fps"),
                       directory=str((concert.dir / "selected-sources" / item["name"]).resolve()))
        if info.get("audio_decoder"):
            current["audio_decoder"] = info["audio_decoder"]
        data.setdefault("songs", {})[item["name"]] = current
        data.setdefault("source", current["source"])
        write_json(concert.dir / "vertical_source.json", data)
        return current


def original_source(concert, item):
    directory = concert.song_dir(item)
    event = concert.load("info")
    policy = read_json(concert.dir / "vertical_source.json", {})
    selected = policy.get("songs", {}).get(item["name"])
    if selected:
        source = Path(selected.get("source") or policy.get("source"))
        if not source.is_file():
            raise FileNotFoundError("指定片源未挂载，不自动切换版本")
        return source
    override = read_json(directory / "song.json", {}).get("source_file")
    sources = [Path(override or ""), Path(event.get("source_file") or ""), concert.source, directory / "source.mp4"]
    if concert.slug == "singles":
        sources.append(POSTS / item["name"] / "source.mp4")
    source = next((path for path in sources if path.is_file()), None)
    if source is None:
        raise FileNotFoundError("封面选帧需要原始视频，请接入原片后重试")
    return source
