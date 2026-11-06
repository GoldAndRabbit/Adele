import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow.live.paths import write_json
from workflow.vertical_cover import original_source
from workflow.vertical_source import prepare
from workflow.vertical_workflow import revision


class SelectedPortraitSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.song = self.root / 'song'; self.song.mkdir()
        self.master = self.root / '720.mkv'; self.master.write_bytes(b'old master')
        self.ts = self.root / 'broadcast.ts'; self.ts.write_bytes(b'ts master')
        self.output = self.root / 'prepared'
        self.c = SimpleNamespace(dir=self.root, slug='fixture', source=self.master,
            song_dir=lambda item:self.song, load=lambda key:{'source_file':str(self.master)})
        self.item = {'name':'song'}

    def policy(self, kind, source):
        write_json(self.root/'vertical_source.json', {'source':str(self.ts),'songs':{'song':{
            'source':str(source),'kind':kind,'slice':[20,25],'directory':str(self.output)}}})

    def test_missing_selected_ts_never_falls_back_to_720(self):
        self.policy('ts', self.ts)
        self.assertEqual(original_source(self.c,self.item),self.ts)
        self.ts.unlink()
        with self.assertRaises(FileNotFoundError): original_source(self.c,self.item)

    def test_720_preparation_uses_override_without_deinterlacing(self):
        self.policy('720p',self.master)
        def fake_run(command,**kwargs): Path(command[-1]).write_bytes(b'prepared')
        with patch('workflow.vertical_source.subprocess.run',side_effect=fake_run) as run:
            result=prepare(self.c,self.item)
            command=run.call_args.args[0]
            self.assertEqual(command[command.index('-i')+1],str(self.master))
            self.assertNotIn('bwdif=mode=send_field:parity=tff:deint=all',command)
            self.assertEqual((self.song/'vertical/original-selected.mp4').resolve(),result.resolve())
            prepare(self.c,self.item)
            self.assertEqual(run.call_count,1)

    def test_browser_revision_tracks_subtitles_not_burned_preview(self):
        (self.song/'subs').mkdir();(self.song/'vertical').mkdir()
        captions=self.song/'subs/lyrics.ass';captions.write_text('caption A')
        write_json(self.song/'song.json',{'preview_mode':'browser','source_file':str(self.master)})
        first=revision(self.song)
        self.assertIsNotNone(first)
        (self.song/'vertical/full.mp4').write_bytes(b'old unrelated render')
        self.assertEqual(first,revision(self.song))
        captions.write_text('caption B')
        self.assertNotEqual(first,revision(self.song))
