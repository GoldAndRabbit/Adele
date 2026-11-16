from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from workflow import stream_delivery as stream
from workflow import dual_platform, dual_render


class StreamDeliveryTests(unittest.TestCase):
    def test_empty_audio_success_recovers_using_same_decoder_without_input_seek(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root/'audio.flac'
            audio.write_bytes(b'header only')
            def probe(path):
                return {'streams': [{'codec_type': 'audio'}], 'format':
                        {'duration': '200'} if audio.read_bytes() == b'full audio' else {}}
            def extract(command, **kwargs):
                self.assertEqual(command[command.index('-c:a')+1], 'eac3_at')
                self.assertLess(command.index('-i'), command.index('-ss'))
                self.assertEqual(command[command.index('-af')+1],'aresample=async=1:first_pts=0')
                audio.write_bytes(b'full audio')
            with patch.object(stream.subprocess, 'run', side_effect=extract) as run:
                mode = stream.recover_audio({'slice': [720, 920], 'audio_decoder': 'eac3_at'},
                                            root/'source.mkv', audio, root, probe, ['ffmpeg','-y'])
                self.assertEqual(mode, 'decode_from_start')
                run.assert_called_once()

    def test_audio_recovery_failure_stops_before_video_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(stream.subprocess, 'run'):
                with self.assertRaisesRegex(RuntimeError, '停止插帧'):
                    stream.recover_audio({'slice': [0, 5]}, root/'source', root/'audio.flac', root,
                                         lambda path: {'streams': []}, ['ffmpeg','-y'])

    def test_missing_final_audio_is_not_mistaken_for_a_complete_video(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(dual_platform, 'probe', return_value={
                'streams': [{'codec_type': 'video'}]}), patch('workflow.content_check.require_job'):
            with self.assertRaisesRegex(ValueError, '缺少有效视频或音轨'):
                dual_platform.finish_outputs(Path(tmp), {'slice': [0, 5],
                    'delivery_platforms': ['bilibili']}, {}, [('bilibili', Path(tmp)/'video.pending.mp4')])

    def test_scene_detector_preserves_existing_cut_and_flash_behavior(self):
        def frames(values):
            return np.array([np.full((36, 64), n, dtype=np.uint8) for n in values]).tobytes()
        self.assertEqual(stream.scene_cuts(frames([0, 0, 80, 80, 80])), (5, [2]))
        # Preserve the existing detector: suppress the flash's leading edge.
        self.assertNotIn(2, stream.scene_cuts(frames([0, 0, 80, 0, 0]))[1])
        self.assertEqual(stream.scene_cuts(frames([0, 0, 80, 80, 80]), ts=True), (5, [2]))
        self.assertEqual(stream.scene_cuts(frames([0, 0, 80, 0, 0]), ts=True)[1], [3])
        with self.assertRaises(ValueError):
            stream.scene_cuts(b'')

    def test_one_failed_stage_stops_and_reaps_its_pipeline_peers(self):
        producer = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        encoder = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(7)'])
        start = time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError, '流式制作进程失败'):
                stream.wait_pipeline([producer, encoder])
            self.assertIsNotNone(producer.poll())
            self.assertEqual(encoder.returncode, 7)
            self.assertLess(time.monotonic()-start, 5)
        finally:
            stream.reap([producer, encoder])

    def test_single_channel_routes_to_stream_and_dual_channel_keeps_shared_master(self):
        with tempfile.TemporaryDirectory() as tmp, patch('workflow.content_check.require_job'):
            root = Path(tmp)
            policy = {'kind': 'original', 'slice': [10, 12],
                      'delivery_platforms': ['bilibili'], 'single_channel_pipeline': 'stream'}
            pending = root/'bilibili-4k60.pending.mp4'
            with patch.object(stream, 'encode', return_value=[('bilibili', pending)]) as encode, patch.object(
                    dual_platform, 'finish_outputs') as finish, patch.object(dual_render, 'save'):
                dual_platform.encode_job(policy, root/'source.mkv', root, root, root)
                self.assertEqual(encode.call_args.args[4], 'bilibili')
                manifest = finish.call_args.args[2]
                self.assertEqual(manifest['pipeline'], 'stream')
                self.assertFalse(manifest['intermediate_video'])
                self.assertFalse((root/'master60.mkv').exists())
            # Both selected: the stream entry must never receive the job.
            policy['delivery_platforms'] = ['bilibili', 'douyin']
            with patch.object(stream, 'encode') as encode, patch(
                    'workflow.original_master.prepare', side_effect=RuntimeError('legacy shared master')):
                with self.assertRaisesRegex(RuntimeError, 'legacy shared master'):
                    dual_platform.encode_job(policy, root/'source.mkv', root, root, root)
                encode.assert_not_called()


if __name__ == '__main__':
    unittest.main()
