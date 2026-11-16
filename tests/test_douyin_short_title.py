import unittest
from workflow.vertical_post import submission

class ShortTitleTest(unittest.TestCase):
    def make(self, title, artist='Dua Lipa', zh='杜阿·利帕', **song):
        return submission({'song': {'title': title, 'artist': artist, **song},
                           'event_short': '2024伦敦现场'},
                          '2024年杜阿·利帕皇家阿尔伯特音乐厅演唱会', zh)

    def test_keeps_song_and_artist(self):
        result = self.make('Training Season')
        self.assertIn('Training Season', result['title'])
        self.assertIn('杜阿·利帕', result['title'])
        self.assertEqual(result['title_chars'], 30)

    def test_long_song_uses_existing_translation(self):
        result = self.make('Does Anybody Really Know What Time It Is?', title_zh='谁真的知道现在几点')
        self.assertIn('谁真的知道现在几点', result['title'])
        self.assertTrue('杜阿·利帕' in result['title'] or 'Dua Lipa' in result['title'])
        self.assertLessEqual(result['title_chars'], 30)

    def test_impossible_combination_reports_missing_room(self):
        with self.assertRaises(ValueError):
            self.make('Does Anybody Really Know What Time It Is?')

    def test_medley_keeps_song_names_when_they_fit(self):
        result = self.make('One / Two / Three', 'Chicago & Robin Thicke', '芝加哥乐队 & 罗宾·西克')
        self.assertIn('One / Two / Three', result['title'])
        self.assertIn('芝加哥乐队', result['title'])
        self.assertLessEqual(result['title_chars'], 30)

if __name__ == '__main__':
    unittest.main()
