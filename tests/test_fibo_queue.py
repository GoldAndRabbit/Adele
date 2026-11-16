import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from workflow.live.paths import write_json
from workflow import fibo_concert

class Concert:
    slug='fixture'
    def __init__(self,path):self.dir=path
    def song_items(self):return [{'name':'one'},{'name':'two'}]

class FiboQueueTests(unittest.TestCase):
    def test_subset_uses_standard_generator_without_requiring_unselected_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=Concert(root)
            write_json(root/'fibo-cover-plan.json',{'one':{'reference':'one.jpg'}})
            with patch.object(fibo_concert,'ROOT',root),patch.object(fibo_concert,'generate_one',return_value={'song':'one','status':'awaiting_visual_review'}) as generate:
                fibo_concert.run(c,root/'model',['one'])
            self.assertEqual(generate.call_count,1)
            self.assertEqual(generate.call_args.args[1]['name'],'one')
    def test_default_full_show_still_requires_every_song_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_json(root/'fibo-cover-plan.json',{'one':{}})
            with self.assertRaises(ValueError):fibo_concert.run(Concert(root),root/'model')
