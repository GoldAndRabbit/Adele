import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from unittest.mock import Mock

from workflow.fibo_reference import reselect
from workflow.fibo_concert import generate_one

from workflow.reviewed_cover import compose_crop, digest, publish, stage
from workflow.live.paths import write_json


class ReviewedCoverTests(unittest.TestCase):
    def test_portrait_uses_full_height_source_around_reviewed_lead(self):
        frame = Image.new('RGB', (160, 90), '#242c40')
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 0, 159, 4), fill='red')
        draw.rectangle((0, 85, 159, 89), fill='blue')
        draw.rectangle((128, 12, 136, 30), fill='green')
        poster = compose_crop(frame, (90, 120), dict(focus=[.5, .25], portrait_focus=[.80, .25], span=[.10, .90]))
        self.assertEqual(poster.getpixel((45, 0)), (255, 0, 0))
        self.assertEqual(poster.getpixel((45, 119)), (0, 0, 255))
        self.assertGreater(poster.getpixel((48, 27))[1], 120)

    def test_changed_candidate_cannot_be_released_with_old_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frame = root/'review.jpg'
            frame.write_bytes(b'original')
            write_json(root/'stage.json', {'files':{str(frame): digest(frame)}})
            review_hash = digest(root/'stage.json')
            frame.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Reviewed file changed'):
                publish(root, review_hash)
            write_json(root/'stage.json', {'files':{}})
            with self.assertRaisesRegex(ValueError, 'changed after visual review'):
                publish(root, review_hash)

    def test_manual_reference_lock_survives_blink_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            concert = Mock()
            concert.dir = Path(folder)
            write_json(concert.dir/'fibo-cover-plan.json',
                       {'song': {'reference_lock': {'source_time': 99}}})
            with self.assertRaisesRegex(ValueError, 'explicitly reviewed reference'):
                reselect(concert, {'name': 'song'})

    def test_changed_reference_must_not_start_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            concert = Mock()
            concert.song_dir.return_value = root
            source = root/'covers/ai/reference.jpg'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'previous frame')
            spec = dict(reference=source.name, source_time=99,
                        reference_lock=dict(source_time=99, reference_sha256=digest(source)))
            source.write_bytes(b'different frame')
            with self.assertRaisesRegex(ValueError, '已确认'):
                generate_one(concert, {'name':'song'}, spec, root, root/'weights')

    def test_full_ai_request_rejects_source_treatment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for job in ({'mode':'oil', 'input':'original.jpg'},
                        {'mode':'oil', 'art':'generated.png', 'palette':'generated.png'}):
                write_json(root/'request.json', job)
                with self.assertRaisesRegex(ValueError, '模型直接输出'):
                    stage(root/'request.json', root/'output')
                self.assertFalse((root/'output').exists())
