import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from workflow.live.paths import read_json, write_json
from workflow.seedream_cover import generate_trial


class SeedreamTrialTest(unittest.TestCase):
    def test_three_candidates_resume_without_paid_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for i in range(3):
                Image.new('RGB', (32, 32), (i * 80, 0, 0)).save(root / f'reference-{i}.png')
            plan = root / 'plan.json'
            write_json(plan, dict(candidates=[dict(label=str(i), prompt=str(i),
                reference=f'reference-{i}.png', source_time=12+i) for i in range(3)]))
            concert = SimpleNamespace(song_dir=lambda item: root)
            (root / 'covers/ai').mkdir(parents=True)
            write_json(root / 'covers/ai/masters.json', [{'file': 'previous.png', 'source_time': 0}])
            image = io.BytesIO()
            Image.new('RGB', (64, 36)).save(image, format='PNG')
            response = Mock(ok=True, headers={}, json=lambda: {'data': [{'url': 'https://example.com/image'}]})
            download = Mock(content=image.getvalue())
            def render(c, item, output, label):
                return [{'master': label + '.png'}]
            with patch.dict('os.environ', {'ARK_API_KEY': 'test-only'}), \
                 patch('workflow.seedream_cover.requests.post', return_value=response) as post, \
                 patch('workflow.seedream_cover.requests.get', return_value=download), \
                 patch('workflow.seedream_cover.render_variants', side_effect=render):
                generate_trial(concert, {}, plan)
                generate_trial(concert, {}, plan)
                self.assertEqual(post.call_count, 3)
                self.assertEqual(len({call.kwargs['json']['image'] for call in post.call_args_list}), 3)
                self.assertEqual(len(read_json(root / 'covers/ai/masters.json')), 4)
                self.assertEqual([r['source_time'] for r in read_json(root / 'covers/ai/masters.json')], [0,12,13,14])

    def test_uncertain_failure_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new('RGB', (32, 32)).save(root / 'reference.png')
            plan = root / 'plan.json'
            write_json(plan, dict(reference='reference.png', candidates=[dict(label='one', prompt='one')]))
            concert = SimpleNamespace(song_dir=lambda item: root)
            with patch.dict('os.environ', {'ARK_API_KEY': 'test-only'}), \
                 patch('workflow.seedream_cover.requests.post', side_effect=TimeoutError) as post:
                for _ in range(2):
                    with self.assertRaises(RuntimeError):
                        generate_trial(concert, {}, plan)
                self.assertEqual(post.call_count, 1)
                self.assertFalse((root / 'covers/ai/masters.json').exists())


if __name__ == '__main__':
    unittest.main()
