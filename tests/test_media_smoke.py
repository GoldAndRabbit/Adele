"""Opt-in real Apple encoding tests, using synthetic two-second inputs only.

ADELE_MEDIA_SMOKE=1 .venv/bin/python -m unittest tests.test_media_smoke
ADELE_REMOTE_SMOKE=user@host additionally verifies SSH execution and return.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

from PIL import Image
import pysubs2

from workflow import content_check, delivery
from workflow.runtime import sha


@unittest.skipUnless(os.environ.get("ADELE_MEDIA_SMOKE") == "1", "real media smoke is opt-in")
class MediaSmokeTests(unittest.TestCase):
    def prepare(self, root, rate):
        source = root / "synthetic.mkv"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                        "-i", f"testsrc2=size=1280x720:rate={rate}:duration=2",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2",
                        "-pix_fmt", "yuv420p", "-c:a", "flac", "-sample_fmt", "s32",
                        "-bits_per_raw_sample", "24", str(source)], check=True)
        output = root / "outputs"
        output.mkdir()
        Image.new("RGBA", (1080, 1920)).save(output / "header.png")
        for kind, size in (("landscape", (3840, 2054)), ("portrait", (1080, 608))):
            Image.new("L", size, 255).save(output / (kind + "-mask.png"))
            captions = pysubs2.SSAFile()
            captions.events.append(pysubs2.SSAEvent(start=0, end=2000, text="Workflow smoke / 流程验证"))
            captions.save(str(output / (kind + ".ass")))
        (output / "watermark.json").write_text(json.dumps({"items": []}))
        identity = content_check.source_identity(source)
        report = {"mode": "prepared_preview", "status": "not_requested",
                  "fingerprint": hashlib.sha256(b"synthetic fixture").hexdigest(),
                  "input": {"concert": "__workflow_smoke__", "song": "fixture",
                            "source": identity, "slice": [0, 2]}}
        policy = {"kind": "original", "source": str(source), "slice": [0, 2],
                  "delivery_platforms": ["bilibili"], "single_channel_pipeline": "stream",
                  "content_check": content_check.job_certificate(report, output, sha(source))}
        (output / "policy.json").write_text(json.dumps(policy))
        return source, output

    def assert_product(self, output):
        data = json.loads((output / "products.json").read_text())
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["pipeline"], "stream")
        self.assertFalse(data["intermediate_video"])
        self.assertEqual(len(data["items"]), 1)
        row = data["items"][0]
        self.assertEqual((row["width"], row["height"], row["fps"]), (3840, 2160, 60))
        self.assertEqual(row["sha256"], sha(output / row["file"]))
        self.assertFalse(any(output.glob("frames*")))

    def test_local_native60_and_interpolated30(self):
        delivery.CACHE.mkdir(parents=True, exist_ok=True)
        for rate in (60, 30):
            with self.subTest(rate=rate), tempfile.TemporaryDirectory(dir=delivery.CACHE, prefix="smoke-") as tmp:
                source, output = self.prepare(Path(tmp), rate)
                delivery.worker(output, source)
                self.assert_product(output)

    @unittest.skipUnless(os.environ.get("ADELE_REMOTE_SMOKE"), "remote smoke requires an explicit host")
    def test_remote_interpolation_and_checksum_return(self):
        with tempfile.TemporaryDirectory(dir=delivery.CACHE, prefix="smoke-") as tmp:
            source, output = self.prepare(Path(tmp), 30)
            run_id = "smoke-" + uuid.uuid4().hex
            remote = delivery.Remote(os.environ["ADELE_REMOTE_SMOKE"], Path("~/.ssh/adele_render_worker"), run_id)
            remote.setup()
            try:
                with (Path(tmp) / "remote.log").open("w") as log:
                    remote.render(output, source, sha(source), log)
                self.assert_product(output)
                self.assertNotEqual(json.loads((output / "products.json").read_text())["render_host"], __import__("platform").node())
            finally:
                remote.command("rm", "-rf", remote.repo)
