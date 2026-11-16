import unittest
from workflow.bili_title import build_title, posting_artist

class TitleBudgetTest(unittest.TestCase):
    def test_registered_chinese_credit_survives_english_model_placeholder(self):
        info = {'artist':'Chappell Roan', 'artist_zh':'查普尔·罗恩'}
        cast = {'artist':'Chappell Roan', 'artist_zh':'Chappell Roan'}
        zh, en = posting_artist(cast, info)
        self.assertEqual(build_title(zh, en, 'Kaleidoscope', '万花筒', '', 'Lowlands Festival'),
                         '查普尔·罗恩 Kaleidoscope Chappell Roan 万花筒 Lowlands Festival 欧美现场 Billboard Grammy')

    def test_guest_does_not_inherit_headliner_chinese_credit(self):
        info = {'artist':'Chappell Roan', 'artist_zh':'查普尔·罗恩'}
        self.assertEqual(posting_artist({'artist':'Guest', 'artist_zh':'Guest'}, info), ('Guest','Guest'))
        self.assertEqual(posting_artist({'artist':'Chappell Roan', 'artist_zh':'人工署名'}, info),
                         ('人工署名','Chappell Roan'))

    def test_requested_order(self):
        self.assertEqual(
            build_title('洛德','Lorde','Royals','皇室','格莱美','Grammy'),
            '洛德 Royals 神婆 洛奶 Lorde 皇室 Grammy 欧美现场 Billboard Grammy 中英字幕')

    def test_budget_removes_whole_trailing_fields(self):
        args=('阿黛尔','Adele','Send My Love (To Your New Lover)','致你的新恋人','伦敦现场','An Audience with Adele')
        full=build_title(*args,limit=None)
        title = build_title(*args)
        self.assertTrue(full.startswith(title + " "))
        self.assertTrue(title.endswith(("Billboard", "Grammy", "欧美现场", "中英字幕")))
        remaining = full[len(title):].strip()
        self.assertGreater(len(title) + 1 + len(remaining.split()[0]), 80)
        self.assertLessEqual(len(build_title(*args)),80)
        self.assertTrue(full.startswith('阿黛尔 Send My Love (To Your New Lover) 阿呆 Adele'))

    def test_disturbed_chinese_credit(self):
        title=build_title('Disturbed','Disturbed','The Sound Of Silence','寂静之声','','CONAN')
        self.assertEqual(title,'骚动乐团 The Sound Of Silence Disturbed 寂静之声 CONAN 欧美现场 Billboard Grammy 中英字幕')

    def test_missing_fields_do_not_leave_placeholders(self):
        self.assertEqual(build_title('', 'New Artist', 'Song', '', '', ''),
                         'Song New Artist 欧美现场 Billboard Grammy 中英字幕')

    def test_medley_compacts_performers_and_keeps_complete_first_song(self):
        title = build_title(
            "史蒂维·旺德、安妮·蓝妮克丝、温迪与莉萨",
            "Stevie Wonder & Annie Lennox & Wendy & Lisa",
            "For Once in My Life / The Best Is Yet to Come / Nothing Compares 2 U / Ain't No Sunshine",
            "骄傲的玛丽号", "2024年第66届格莱美颁奖典礼", "66th Annual Grammy Awards")
        self.assertTrue(title.startswith("史蒂维·旺德等 For Once in My Life等串烧"))
        self.assertLessEqual(len(title), 80)
        self.assertNotIn("Annie Lennox", title)
        self.assertNotIn(" / ", title)

    def test_medley_uses_the_same_space_separated_field_order_as_a_single(self):
        self.assertEqual(
            build_title('洛德', 'Lorde', 'Royals / Team', '贵族 / 团队', '', 'Grammy', limit=None),
            '洛德 Royals等串烧 神婆 洛奶 Lorde 贵族等串烧 Grammy 欧美现场 Billboard Grammy 中英字幕')

    def test_mixed_artist_credit_does_not_repeat_english_name_or_nickname(self):
        title = build_title('火星哥 Bruno Mars & 红辣椒乐队',
                            'Bruno Mars & Red Hot Chili Peppers', 'Song', '歌', '', '', limit=None)
        self.assertTrue(title.startswith('火星哥等 Song Bruno Mars等 歌'))
        self.assertEqual(title.count('火星哥'), 1)
        self.assertEqual(title.count('Bruno Mars'), 1)

    def test_song_punctuation_is_preserved_without_inserting_a_separator(self):
        self.assertTrue(build_title('德瑞博士', 'Dr. Dre', 'Still D.R.E.', '', '', '').startswith(
            '德瑞博士 Still D.R.E. Dr. Dre'))

    def test_letter_named_groups_keep_their_identity_in_chinese_credits(self):
        self.assertTrue(build_title('U2乐队', 'U2', 'Atomic City', '原子城', '', '').startswith('U2乐队 Atomic City U2'))
        self.assertTrue(build_title('HKT48组合', 'HKT48', 'Song', '歌', '', '').startswith('HKT48组合 Song HKT48'))

    def test_ampersand_inside_band_name_is_not_a_guest_separator(self):
        title = build_title('蒙福之子乐团', 'Mumford & Sons', 'I Will Wait', '我会等你', '', '')
        self.assertTrue(title.startswith('蒙福之子乐团 I Will Wait Mumford & Sons'))
        self.assertNotIn('等', title.split(' I Will Wait')[0])

    def test_oversized_lead_is_rejected_instead_of_dropping_the_song(self):
        with self.assertRaises(ValueError):
            build_title('歌手', 'Artist', 'Very Long Song ' * 10, '', '', '')

    def test_tiny_desk_medley_keeps_event_and_omits_nickname_to_fit(self):
        title = build_title('奥利维亚·罗德里戈', 'Olivia Rodrigo',
                            'Love Is Embarrassing / Vampire / Lacy / Making The Bed',
                            '爱情真丢人 / 吸血鬼 / 莱西 / 自作自受',
                            'Tiny Desk 音乐会 2023', 'Tiny Desk Concert 2023')
        self.assertEqual(title, '奥利维亚·罗德里戈 Love Is Embarrassing等串烧 Olivia Rodrigo 爱情真丢人等串烧 Tiny Desk Concert 2023')
        self.assertEqual(len(title), 80)

    def test_verified_shorter_event_is_used_before_omitting_song_translation(self):
        title = build_title('嘎嘎小姐', 'Lady Gaga', 'How Bad Do U Want Me', '到底多想要我',
                            '科切拉音乐节2025', 'Coachella Valley Music and Arts Festival')
        self.assertIn('科切拉音乐节2025', title)
        self.assertIn('到底多想要我', title)
        self.assertLessEqual(len(title),80)

    def test_unfittable_event_requires_review_instead_of_being_dropped(self):
        with self.assertRaisesRegex(ValueError, '演出简称'):
            build_title('歌手', 'Artist', 'Complete song name', '歌名', '', 'Complete event name ' * 8)

    def test_full_show_does_not_repeat_event_already_in_translation(self):
        title = build_title('嘎嘎小姐', 'Lady Gaga', 'Super Bowl LI Halftime Show',
                            '2017超级碗中场秀', '2017超级碗中场秀', 'Super Bowl LI Halftime Show 2017')
        self.assertEqual(title.count('Super Bowl'), 1)
        self.assertIn('2017超级碗中场秀', title)

    def test_full_show_recognizes_year_before_or_after_event_name(self):
        title = build_title('碧昂丝等', 'Beyoncé & Destiny\'s Child', 'Super Bowl XLVII Halftime Show',
                            '2013超级碗中场秀', '超级碗中场秀2013', 'Super Bowl XLVIIl Halftime Show 2013')
        self.assertEqual(title.count('超级碗中场秀'), 1)
        self.assertIn('2013超级碗中场秀', title)

    def test_screenshot_keywords_are_not_cut_into_fragments(self):
        title = build_title("洛德", "Lorde", "Green Light", "绿灯", "",
                            "iHeartRadio Music Festival 2017")
        self.assertTrue(title.endswith("Billboard"))
        self.assertLessEqual(len(title), 80)
        full = build_title("洛德", "Lorde", "Green Light", "绿灯", "",
                           "iHeartRadio Music Festival 2017", limit=None)
        self.assertGreater(len(title + " Grammy"), 80)
        self.assertTrue(full.startswith(title))

    def test_collaboration_uses_first_performer_without_calling_it_a_medley(self):
        title = build_title(
            "斯坦利·克拉克 & 奇克·科里亚 & 肯尼·加勒特",
            "Stanley Clarke & Chick Corea & Kenny Garrett",
            "Take Five", "", "2013年第55届格莱美", "55th Annual Grammy Awards")
        self.assertTrue(title.startswith("斯坦利·克拉克等 Take Five Stanley Clarke等"))
        self.assertNotIn("Chick", title)
        self.assertNotIn("奇克", title)
        self.assertNotIn("串烧", title)
        self.assertLessEqual(len(title), 80)
