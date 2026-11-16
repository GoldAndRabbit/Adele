import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow import delivery_config
from workflow import douyin_queue
from workflow import original_master


class DeliveryConfigTests(unittest.TestCase):
    def test_bilibili_only_delivery_does_not_require_douyin(self):
        with tempfile.TemporaryDirectory() as tmp:
            song = Path(tmp)
            products = song / 'products'
            products.mkdir()
            video = products / 'bili.mp4'
            video.write_bytes(b'finished video')
            (products / 'products.json').write_text(json.dumps({
                'status': 'ready', 'items': [
                    {'platform': 'bilibili', 'file': 'bili.mp4', 'status': 'ready'}]}))
            self.assertTrue(delivery_config.products_ready(song, ['bilibili']))
            self.assertFalse(delivery_config.products_ready(song, ['bilibili', 'douyin']))
            video.unlink()
            self.assertFalse(delivery_config.products_ready(song, ['bilibili']))

    def test_explicit_job_selection_is_independent_of_default(self):
        with patch.object(delivery_config, 'read_json', return_value={'render_platforms': ['bilibili']}):
            self.assertEqual(delivery_config.render_platforms(), ('bilibili',))
            self.assertEqual(delivery_config.render_platforms(['douyin']), ('douyin',))
            for invalid in ([], ['unknown'], ['bilibili', 'bilibili'], 'bilibili'):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    delivery_config.render_platforms(invalid)

    def test_disabled_douyin_collections_are_not_queued(self):
        with patch.object(delivery_config, 'collection_platforms', return_value=('bilibili',)), patch.object(
                douyin_queue, 'write_json') as write:
            douyin_queue.enqueue_collection({'slug': 'concert', 'songs': ['one']})
            write.assert_not_called()

    def test_master_uses_confirmed_audio_decoder_and_hdr_preview_conversion(self):
        info = {'streams': [{'codec_type': 'video', 'r_frame_rate': '30/1',
                            'width': 3840, 'height': 2160,
                            'color_transfer': 'arib-std-b67', 'color_space': 'bt2020c'}]}
        with patch.object(original_master.sp, 'run', side_effect=RuntimeError('stop before encode')) as run:
            with self.assertRaisesRegex(RuntimeError, 'stop before encode'):
                original_master.prepare(Path('source.mkv'), 200, 160, Path('/internal'),
                                        lambda source: info, ['ffmpeg'], audio_decoder='eac3_at')
        args = run.call_args.args[0]
        self.assertLess(args.index('eac3_at'), args.index('-i'))
        filters = args[args.index('-vf')+1]
        self.assertIn('matrixin=bt2020nc', filters)
        self.assertIn('zscale=p=bt709,tonemap=mobius,zscale=t=bt709:m=bt709:r=limited', filters)
