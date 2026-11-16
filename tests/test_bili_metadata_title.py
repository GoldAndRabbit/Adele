import unittest

from post_bili.metadata_quality import fingerprint, issues


class MetadataTitleRulesTest(unittest.TestCase):
    def test_legacy_policy_accepts_whole_field_trimming_without_old_prefix_or_minimum(self):
        fields = {'title':'洛德 Green Light 神婆 洛奶 Lorde 绿灯',
                  'desc':'歌曲。'*200+'\n\n'+'演出。'*200+'\n\n'+'歌词。'*200,
                  'tag':['音乐分享官','完整演出名称']+[f'标签{i}' for i in range(10)]}
        policy = {'required_event':'完整演出名称',
                  'reviewed_fingerprint':fingerprint(fields['title'],fields['desc'],fields['tag'])}
        self.assertEqual(issues(fields,policy),[])

    def test_reviewed_title_still_respects_platform_maximum(self):
        fields = {'title':'长'*81,'desc':'正文','tag':[]}
        policy = {'title_format':'reviewed_current',
                  'reviewed_fingerprint':fingerprint(fields['title'],fields['desc'],fields['tag'])}
        self.assertTrue(any('1–80' in message for message in issues(fields,policy)))
