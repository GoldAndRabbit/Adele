import unittest

from workflow.selection_library import exclusion_reason, select_videos
from workflow.selection_download import build_queue


def video(rank, title='Artist - Song (Music Video)', duration=180):
    return dict(rank=rank, video_id=f'video{rank}', title=title,
                duration_seconds=duration, is_song=True, url=f'https://youtu.be/video{rank}')


class SelectionLibraryTests(unittest.TestCase):
    def test_popular_order_and_replacements_from_top_50(self):
        rows = [video(i, 'Artist - Song (Lyric Video)' if i <= 20 else 'Artist - Music Video')
                for i in range(1, 61)]
        selected, excluded = select_videos(rows)
        self.assertEqual([v['rank'] for v in selected], list(range(21, 46)))
        self.assertEqual(len(excluded), 20)

    def test_never_fills_shortfall_from_beyond_50(self):
        rows = [video(i, 'Artist - Official Audio' if i <= 30 else 'Artist - Music Video')
                for i in range(1, 61)]
        selected, _ = select_videos(rows)
        self.assertEqual([v['rank'] for v in selected], list(range(31, 51)))

    def test_filter_variants_and_duration_boundary(self):
        for title in ['Artist - Lyrics', 'Artist - Official Lyric Video', 'Artist - Official Audio']:
            self.assertEqual(exclusion_reason(video(1, title)), 'lyric_or_audio')
        self.assertEqual(exclusion_reason(video(1, duration=119)), 'shorter_than_120_seconds')
        self.assertIsNone(exclusion_reason(video(1, duration=120)))
        self.assertIsNone(exclusion_reason(video(1, 'Artist - Live at Wembley')))

    def test_queue_independently_rejects_stale_audio_rows(self):
        artist = dict(name='Artist', id='artist', videos=[video(1), video(2, 'Song (Audio)'), video(3, duration=119)])
        self.assertEqual([v['video_id'] for v in build_queue({'artists': [artist]})], ['video1'])
