import unittest
from workflow.bili_title import build_title

class TitleBudgetTest(unittest.TestCase):
    def test_short_title_is_unchanged(self):
        args=('洛德','Lorde','Royals','皇室','格莱美','Grammy')
        self.assertEqual(build_title(*args),build_title(*args,limit=None))

    def test_long_title_preserves_song_and_performer(self):
        args=('阿黛尔','Adele','Send My Love (To Your New Lover)','致你的新恋人','阿黛尔伦敦帕拉迪姆剧院现场','An Audience with Adele')
        title=build_title(*args,year=2021)
        self.assertLessEqual(len(title),80)
        self.assertIn(args[2],title)
        self.assertTrue(title.startswith('Adele '))
        self.assertNotIn('…',title)
        self.assertGreater(len(build_title(*args,year=2021,limit=None)),80)

    def test_group_credit_uses_known_chinese_names(self):
        title=build_title('九寸钉 & 石器时代皇后 & 戴夫·格罗尔 & 林赛·白金汉','Nine Inch Nails, Queens of the Stone Age, Dave Grohl & Lindsey Buckingham','Copy of A / My God Is the Sun','复制品 / 我的神是太阳','第56届格莱美颁奖典礼','Grammy Awards',year=2014)
        self.assertLessEqual(len(title),80)
        self.assertIn('Copy of A / My God Is the Sun',title)
        self.assertNotIn('...',title)

    def test_no_model_can_replace_performer(self):
        title=build_title('洛德','Lorde','Girl, so confusing','女孩，如此困惑','奥斯汀城市极限音乐节','ACL Festival',year=2026)
        self.assertTrue(title.startswith('Lorde '))
        self.assertNotIn('Charli',title)
