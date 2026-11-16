import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from post_bili.full_library import sync_completed_covers
from workflow.live.paths import read_json, write_json


class CompletedCoverTests(unittest.TestCase):
    def test_unchanged_metadata_does_not_reupload_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            metadata = {'title': 'Collection', 'cover_path': 'dedicated-v1.jpg'}
            write_json(folder / 'collection-source-sample.json', metadata)
            state = {'batches': {'sample': {'cover_sync_error': 'old unnecessary retry'}}}
            with patch('post_bili.full_library.latest_collection', return_value=metadata), \
                    patch('post_bili.full_library.collection_id') as upload:
                sync_completed_covers(folder, ['sample'], state, Mock())
            upload.assert_not_called()
            self.assertNotIn('cover_sync_error', state['batches']['sample'])

    def test_cover_system_exit_does_not_abort_other_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            metadata = {'title': 'Updated', 'cover_path': 'dedicated-v2.jpg'}
            state = {'batches': {'one': {}, 'two': {}}}
            save = Mock()
            with patch('post_bili.full_library.latest_collection', return_value=metadata), \
                    patch('post_bili.full_library.collection_id', side_effect=[SystemExit('cover unavailable'), 123]):
                sync_completed_covers(folder, ['one', 'two'], state, save)
            self.assertIn('cover unavailable', state['batches']['one']['cover_sync_error'])
            self.assertEqual(read_json(folder / 'collection-source-two.json'), metadata)
            self.assertFalse((folder / 'collection-source-one.json').exists())
            self.assertEqual(save.call_count, 2)

    def test_rate_limit_defers_remaining_cover_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {'batches': {'one': {}, 'two': {}}}
            with patch('post_bili.full_library.latest_collection', return_value={'title': 'Updated'}), \
                    patch('post_bili.full_library.collection_id', side_effect=SystemExit('-702 请求频率过高')) as upload:
                sync_completed_covers(Path(tmp), ['one', 'two'], state, Mock())
            upload.assert_called_once()
