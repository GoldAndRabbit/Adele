import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from server import selection_preview as preview


class SelectionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'downloads'
        (self.root / '_queue').mkdir(parents=True)
        self.source = self.root / 'Artist/song.mkv'
        self.source.parent.mkdir()
        self.source.write_bytes(b'original media')
        self.row = dict(video_id='abcdefghijk', title='Song', artist='Artist', status='completed', path=str(self.source))
        self.write_queue()
        self.patch = patch.object(preview, 'storage', return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        app = FastAPI()
        app.include_router(preview.router)
        self.client = TestClient(app)

    def write_queue(self):
        (self.root / '_queue/queue.json').write_text(json.dumps({'items': [self.row]}))

    def test_listing_and_status_do_not_load_or_prepare_media(self):
        with patch.object(preview, 'Thread') as thread, patch.object(preview, 'build') as build:
            response = self.client.get('/api/selection-downloads')
            self.assertEqual(response.json()['videos']['abcdefghijk']['preview_url'], '/selection-preview.html?id=abcdefghijk')
            self.assertEqual(self.client.get('/api/selection-downloads/abcdefghijk/preview?compatible=true').json()['status'], 'not_started')
            thread.assert_not_called()
            build.assert_not_called()
        self.assertFalse((self.root / '_previews').exists())

    def test_original_playback_never_builds_a_preview_and_supports_ranges(self):
        with patch.object(preview, 'Thread') as thread, patch.object(preview, 'build') as build:
            for method in (self.client.get, self.client.post):
                row = method('/api/selection-downloads/abcdefghijk/preview').json()
                self.assertEqual(row['status'], 'ready')
                self.assertEqual(row['mode'], 'original')
                self.assertEqual(row['media_url'], '/api/selection-downloads/abcdefghijk/original')
            response = self.client.get(row['media_url'], headers={'Range': 'bytes=0-7'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, b'original')
            thread.assert_not_called()
            build.assert_not_called()
        self.assertFalse((self.root / '_previews').exists())

    def test_listing_reports_original_specs_without_probing_video(self):
        self.row['media'] = {'streams': [{'codec_type': 'audio'},
            {'codec_type': 'video', 'width': 3840, 'height': 2160, 'r_frame_rate': '60000/1001'}]}
        self.write_queue()
        with patch.object(preview.subprocess, 'run') as run:
            row = self.client.get('/api/selection-downloads').json()['videos']['abcdefghijk']
            self.assertEqual(row['fps'], 59.94)
            self.assertEqual(row['resolution'], '2160p（4K）')
            run.assert_not_called()
        self.assertEqual(preview.source_specs({}), {'fps': None, 'resolution': None})
        self.assertEqual(preview.source_specs({'media': {'streams': [
            {'codec_type': 'video', 'width': 1280, 'height': 720,
             'avg_frame_rate': '0/0', 'r_frame_rate': '25/1'}]}}),
            {'fps': 25.0, 'resolution': '720p'})

    def test_click_starts_one_job_and_ready_media_supports_byte_ranges(self):
        target = preview.target_for(self.source, self.row['video_id'])
        with patch.object(preview, 'Thread') as thread:
            for _ in range(2):
                self.assertEqual(self.client.post('/api/selection-downloads/abcdefghijk/preview?compatible=true').json()['status'], 'building')
            self.assertEqual(thread.call_count, 1)
        target.parent.mkdir()
        target.write_bytes(b'0123456789')
        response = self.client.get('/api/selection-downloads/abcdefghijk/media', headers={'Range':'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'2345')
        self.assertEqual(self.client.get('/api/selection-downloads/abcdefghijk/preview').json()['status'], 'ready')

    def test_pending_missing_and_escaped_media_are_not_served(self):
        self.row['status'] = 'pending'
        self.write_queue()
        self.assertEqual(self.client.post('/api/selection-downloads/abcdefghijk/preview').status_code, 404)
        outside = Path(self.temp.name) / 'private.mkv'
        outside.write_bytes(b'private')
        self.row.update(status='completed', path=str(outside))
        self.write_queue()
        self.assertEqual(self.client.get('/api/selection-downloads/abcdefghijk/preview').status_code, 404)
        self.assertEqual(self.client.get('/api/selection-downloads/not-valid/preview').status_code, 404)
        self.assertEqual(self.client.get('/api/selection-downloads/abcdefghijk/original').status_code, 404)
