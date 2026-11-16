import unittest
from workflow.vertical_post import douyin_description


class DouyinTopicTests(unittest.TestCase):
    def test_extra_song_topic_cannot_push_posting_above_five_topics(self):
        topics=['#演唱会','#歌手','#演出英文名','#昵称','#欧美现场','#歌曲译名']
        body,chosen,text=douyin_description('这是已经确定的简介。',topics)
        self.assertEqual(chosen,topics[:5])
        self.assertEqual(body,'这是已经确定的简介。')
        self.assertNotIn('#歌曲译名',text)
