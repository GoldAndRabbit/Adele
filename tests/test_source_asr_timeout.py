import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import requests
from workflow.live.asr_match import asr_words,decode_sentence

class SourceASRTimeoutTests(unittest.TestCase):
    def test_source_evidence_keeps_the_beginning_of_a_held_sung_word(self):
        sentence={'words':[{'text':' Away','begin_time':2000,'end_time':10000}]}
        self.assertEqual(decode_sentence(sentence,50)[0]['s'],59)
        raw=decode_sentence(sentence,50,clamp_long_words=False)[0]
        self.assertEqual((raw['s'],raw['e']),(52,60))

    def test_source_window_retry_budget_is_bounded_and_failure_is_not_silence(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('sys.modules',{
                'qwen_asr':SimpleNamespace(wav_bytes=lambda y:b'audio')}),\
             patch('requests.post',side_effect=requests.Timeout('stalled window')) as post,\
             patch('time.sleep'):
            cache=Path(tmp)/'cache.json'
            with self.assertRaisesRegex(RuntimeError,'网络失败'):
                asr_words(np.zeros(16000),16000,'unit-test-key',cache,
                          request_timeout=60,attempts=2)
            self.assertEqual(post.call_count,2)
            self.assertTrue(all(c.kwargs['timeout']==60 for c in post.call_args_list))
            self.assertFalse(cache.exists())

if __name__=='__main__':unittest.main()
