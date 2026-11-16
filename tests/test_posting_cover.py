from argparse import Namespace
from datetime import datetime
from pathlib import Path
import os
import tempfile
import unittest

from PIL import Image
from post_bili.upload import generate
from workflow.live.paths import write_json
from workflow.posting_cover import SHANGHAI, active_cover_set, cover_path


class PostingCoverTest(unittest.TestCase):
    def test_rebuild_picks_complete_revision_with_timestamped_platform_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            song = Path(tmp)
            ai = song / 'covers/ai'
            ai.mkdir(parents=True)
            write_json(song / 'post_draft.json', {'song': {'artist': 'Adele', 'title': 'Hello'}})
            write_json(ai / 'masters.json', [{'file': 'next'}, {'file': 'current'}])
            minute = datetime(2026, 11, 10, 16, 23, tzinfo=SHANGHAI).timestamp()
            variants = []
            for master in ('next', 'current'):
                for platform, ratio in [('bili', '16x9'), ('bili', '4x3'), ('douyin', '4x3'), ('douyin', '3x4')]:
                    if master == 'next' and ratio == '3x4':
                        continue
                    path = ai / f'{master}-{platform}-{ratio}.jpg'
                    Image.new('RGB', (8, 8), 'red' if master == 'next' else 'blue').save(path)
                    os.utime(path, (minute, minute))
                    variants.append(dict(master=master, platform=platform+'-ai', ratio=ratio, file=path.name))
            write_json(ai / 'variants.json', variants)
            chosen = active_cover_set(song)
            self.assertEqual(len(chosen), 4)
            for (platform, ratio), source in chosen.items():
                self.assertTrue(source.name.startswith('current-'))
                label = platform.split('-')[0]
                target = Path(cover_path(song, source, label, ratio))
                self.assertEqual(target.name, f'{label}_ai_{ratio}_2611101623.jpg')
                self.assertEqual(target.read_bytes(), source.read_bytes())
            args = Namespace(cover=None, source=None, at=None, tid=None, tid_v2=None, only_self=False)
            page = generate(song, args)
            normal = Path(page['封面16:9'])
            self.assertTrue(normal.samefile(chosen['bili-ai', '16x9']))
            args.cover = ai / 'next-bili-16x9.jpg'
            other = Path(generate(song, args)['封面16:9'])
            self.assertTrue(other.samefile(args.cover))
            self.assertEqual(normal.name, other.name)
            self.assertNotEqual(normal, other)
