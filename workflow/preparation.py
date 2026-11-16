"""Song audio preparation. Local and SSH separation use the same implementation."""
from pathlib import Path
import shlex
import subprocess
import uuid

from workflow.live.paths import ROOT, SEP_PY, read_json, write_json
from workflow.sources import ensure_selection
from workflow.runtime import sha


def prepare_audio(concert, item, *, host="local", key=None, force=False):
    import soundfile as sf
    policy = ensure_selection(concert, item)
    directory = concert.song_dir(item)
    identity = {"source": policy["source"], "slice": policy["slice"]}
    unchanged = read_json(directory / "audio_source.json") == identity
    audio, vocals = directory / "audio.flac", directory / "vocals.wav"
    if unchanged and audio.is_file() and vocals.is_file() and not force:
        return
    from workflow.vertical_source import prepare
    clip = prepare(concert, item)
    pending = directory / "audio.pending.flac"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(clip),
                    "-vn", "-c:a", "flac", "-ar", "48000", "-sample_fmt", "s32", str(pending)], check=True)
    pending.replace(audio)
    temporary = directory / "vocals.pending.wav"
    if host == "local":
        subprocess.run([str(SEP_PY), str(ROOT / "workflow/separate_roformer.py"),
                        str(audio), "-o", str(temporary), "--device", "mps"], check=True)
    else:
        # Reuse the installed GPU environment and model on the second Mac.
        # Model installation is not repeated for each song or hidden behind CPU.
        from workflow.delivery import Remote
        remote = Remote(host, Path(key or "~/.ssh/adele_render_worker"), uuid.uuid4().hex)
        base = "Library/Caches/adele/subtitle-worker"
        job = base + "/jobs/" + uuid.uuid4().hex
        remote.command("mkdir", "-p", job)
        remote.sync(audio, host + ":" + job + "/audio.flac")
        # Synchronize the formal separator, not a batch-specific helper.
        remote.sync(ROOT / "workflow/separate_roformer.py", host + ":" + base + "/workflow/")
        command = [base + "/venv/bin/python", base + "/workflow/separate_roformer.py",
                   job + "/audio.flac", "-o", job + "/vocals.wav", "--device", "mps"]
        remote.command("sh", "-c", "export PATH=/opt/homebrew/bin:$PATH; " + shlex.join(command))
        remote.sync(host + ":" + job + "/vocals.wav", temporary)
    if abs(sf.info(str(audio)).duration - sf.info(str(temporary)).duration) > .3:
        raise ValueError("人声分离结果时长不符，保留已有定稿")
    temporary.replace(vocals)
    for name in ("beats.npy", "pitch.npz", "stereo.npz"):
        (directory / "reports" / name).unlink(missing_ok=True)
    song = read_json(directory / "song.json", {})
    song.update(slice=policy["slice"], source_file=policy["source"])
    write_json(directory / "song.json", song)
    write_json(directory / "audio_source.json", identity)


def remote_subtitles(concert, item, *, host, key=None, force=False):
    """Run separation AND alignment on the selected Mac, then return results.

    The worker receives a song clip and the current formal modules. Model and
    provider environments stay installed on that Mac; no credentials are copied
    or printed. Manual revisions are checked again before installing the return.
    """
    import shutil
    from workflow.delivery import Remote
    from workflow.vertical_source import prepare
    policy = ensure_selection(concert, item)
    directory = concert.song_dir(item)
    clip = prepare(concert, item)
    run_id = uuid.uuid4().hex
    remote = Remote(host, Path(key or "~/.ssh/adele_render_worker"), run_id)
    remote.setup()
    base = "Library/Caches/adele/subtitle-worker"
    # Existing GPU runtime owns its models and credentials. All calls use the
    # same standard modules as local processing, in an isolated project tree.
    bootstrap = """from pathlib import Path
import sys
root=Path.home()/sys.argv[1]
installed=Path.home()/'Library/Caches/adele/subtitle-worker'
for name,target in [('models',installed/'models'),('.venv',installed/'venv'),
                    ('.venv-sep',installed/'venv'),('.env',installed/'.env')]:
    dst=root/name
    if not dst.exists() and target.exists():dst.symlink_to(target)
"""
    remote.command("python3", "-c", bootstrap, remote.repo)
    remote.command("test", "-x", base + "/venv/bin/python")
    song_path = f"{remote.repo}/concerts/{concert.slug}/songs/{item['name']}"
    remote.command("mkdir", "-p", song_path)
    # Copy only bounded song data, with no product, model or full-concert trees.
    files = ["lyrics.txt", "lyrics_sections.txt", "lyrics_source", "zh_fixed.json",
             "zh_notes.json", "title_translation.json", "title_translation_cache.json",
             "post_draft.json", "watermark.json"]
    manual = {name: sha(directory / name) if (directory / name).is_file() else None
              for name in ("zh_fixed.json", "zh_notes.json", "title_translation.json")}
    for name in files:
        if (directory / name).is_file():
            remote.sync(directory / name, host + ":" + song_path + "/")
    remote.sync(clip, host + ":" + song_path + "/preview.mp4")
    folder = directory / "workflow/subtitles" / run_id
    folder.mkdir(parents=True)
    duration = policy["slice"][1] - policy["slice"][0]
    info = {**read_json(concert.info), "source_file": "preview.mp4"}
    write_json(folder / "concert.json", info)
    write_json(folder / "setlist.json", {"items": [item]})
    write_json(folder / "segments.json", {"items": [dict(item, start=0, end=duration)]})
    song = read_json(directory / "song.json", {})
    write_json(folder / "song.json", {**song, "slice": [0, duration], "preview": [0, duration]})
    for name in ("concert.json", "setlist.json", "segments.json"):
        remote.sync(folder / name, host + ":" + f"{remote.repo}/concerts/{concert.slug}/")
    remote.sync(folder / "song.json", host + ":" + song_path + "/")
    # One GPU model/song at a time; subprocess completion releases its memory.
    command = (f'export PATH=/opt/homebrew/bin:$PATH; cd "$HOME/{remote.repo}" && '
               f'"$HOME/{base}/venv/bin/python" -m workflow.preparation '
               + shlex.join([concert.slug, item["name"]]))
    remote.command("sh", "-c", command)
    returned = folder / "returned"
    returned.mkdir()
    for name in ("subs", "watermark.json", "title_translation.json", "vocals.wav", "audio.flac"):
        remote.sync(host + ":" + song_path + "/" + name, str(returned) + "/")
    if policy != ensure_selection(concert, item) or any(
        (sha(directory / name) if (directory / name).is_file() else None) != digest
        for name, digest in manual.items()
    ):
        raise ValueError("字幕制作期间原片边界或人工定稿变化，保留副机结果待处理")
    for name in ("subs", "watermark.json", "title_translation.json", "vocals.wav", "audio.flac"):
        src = returned / name
        dst = directory / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            src.replace(dst)
    write_json(directory / "audio_source.json", {"source": policy["source"], "slice": policy["slice"]})


def subtitle_worker(slug, name):
    """Internal SSH entry, using the regular alignment and translation engine."""
    import sys
    from workflow.live.paths import Concert
    from workflow.song.run import run_song
    sys.path.insert(0, str(ROOT / "workflow"))
    concert = Concert(slug)
    item = concert.item(name)
    directory = concert.song_dir(item)
    audio = directory / "audio.flac"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(directory / "preview.mp4"),
                    "-vn", "-c:a", "flac", "-ar", "48000", "-sample_fmt", "s32", str(audio)], check=True)
    subprocess.run([str(SEP_PY), str(ROOT / "workflow/separate_roformer.py"), str(audio),
                    "-o", str(directory / "vocals.wav"), "--device", "mps"], check=True)
    run_song(slug, name)


if __name__ == "__main__":
    import sys
    subtitle_worker(*sys.argv[1:])
