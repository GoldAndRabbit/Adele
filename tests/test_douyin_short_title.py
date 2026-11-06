import unittest
from workflow.vertical_post import submission
class ShortTitleTest(unittest.TestCase):
 def make(self,title,artist='Dua Lipa',zh='杜阿·利帕',event='2024年杜阿·利帕皇家阿尔伯特音乐厅演唱会'):
  return submission({'song':{'title':title,'artist':artist},'event_short':'2024伦敦现场'},event,zh)
 def test_compacts_event_without_cutting_song_or_name(self):
  r=self.make('Training Season');self.assertEqual(r['title'],'Training Season 杜阿·利帕 2024伦敦现场');self.assertEqual(r['title_chars'],30);self.assertNotIn('…',r['title'])
 def test_long_song_uses_complete_sentence(self):
  r=self.make('Does Anybody Really Know What Time It Is?');self.assertLessEqual(r['title_chars'],30);self.assertNotIn('…',r['title']);self.assertIn('现场演唱',r['title']);self.assertIn('Does Anybody',r['title_full'])
 def test_medley_keeps_complete_label(self):
  r=self.make('One / Two / Three','Chicago & Robin Thicke','芝加哥乐队 & 罗宾·西克');self.assertTrue(r['title'].endswith('歌曲串烧'));self.assertLessEqual(r['title_chars'],30);self.assertNotIn('…',r['title'])
if __name__=='__main__':unittest.main()
