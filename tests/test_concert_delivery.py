import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from workflow import concert_delivery
from workflow.delivery_bundle import posting_paths


class ConcertDeliveryTests(unittest.TestCase):
    def test_unchanged_concert_source_is_hashed_once_and_edit_invalidates_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'source.mp4'
            source.write_bytes(b'original')
            with patch.object(concert_delivery, 'CACHE', folder), patch.object(
                    concert_delivery, 'sha', wraps=concert_delivery.sha) as checksum:
                first = concert_delivery.source_digest(source)
                self.assertEqual(concert_delivery.source_digest(source), first)
                self.assertEqual(checksum.call_count, 1)
                source.write_bytes(b'changed source')
                self.assertNotEqual(concert_delivery.source_digest(source), first)
                self.assertEqual(checksum.call_count, 2)

    def test_running_job_does_not_relabel_an_existing_product(self):
        with tempfile.TemporaryDirectory() as tmp:
            song = Path(tmp)
            products = song / 'products'
            products.mkdir()
            (products / 'video.mp4').touch()
            (products / 'products.json').write_text(json.dumps({
                'render_host': 'first-mac', 'production_log': '/finished.log',
                'items': [{'platform':'douyin', 'status':'ready', 'file':'video.mp4'}]}))
            (song / 'render_status.json').write_text(json.dumps({
                'status':'running', 'executor':'second-mac', 'log':'/current.log'}))
            data = posting_paths(song)['douyin']
            self.assertEqual(data['render_host'], 'first-mac')
            self.assertEqual(data['production_log'], '/finished.log')
            self.assertEqual(data['current_executor'], 'second-mac')

    def test_worker_hashes_returned_outputs_before_coordinator_accepts_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'policy.json').write_text('{}')
            source = folder / 'source.mp4'
            source.touch()
            def fake_encode(policy, source, output, cache, directory):
                self.assertNotEqual(cache, output)
                (output / 'video.mp4').write_bytes(b'rendered')
                (output / 'products.json').write_text(json.dumps({
                    'status':'ready', 'render_host':'worker', 'items':[{'file':'video.mp4'}]}))
            with patch.object(concert_delivery,'CACHE',folder), patch.object(concert_delivery,'encode_job',fake_encode), patch.object(
                    concert_delivery.shutil, 'disk_usage', return_value=SimpleNamespace(free=30*1024**3)), patch.object(
                    concert_delivery,'require_job',return_value={'source_sha256':concert_delivery.sha(source)}):
                concert_delivery.worker(folder,source)
            data = json.loads((folder / 'products.json').read_text())
            self.assertEqual(data['items'][0]['sha256'], concert_delivery.sha(folder/'video.mp4'))
