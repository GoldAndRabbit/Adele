import unittest

from post_bili.edit_cover import complete_body


class CompleteCoverCopyTests(unittest.TestCase):
    def test_cover_edit_uses_full_recorded_copy_instead_of_250_character_preview(self):
        body = '歌曲介绍。' * 300
        self.assertEqual(complete_body(body[:250], [body, None]), body)

    def test_pending_editor_copy_is_preserved_when_public_copy_is_older(self):
        current = '当前已保存的完整介绍。' * 180
        older = '原先公开的介绍。' * 180
        self.assertEqual(complete_body(current, [older, current]), current)

    def test_shared_preview_cannot_choose_between_two_unverified_versions(self):
        prefix = '前' * 250
        with self.assertRaises(ValueError):
            complete_body(prefix, [prefix + '版本甲', prefix + '版本乙'])

    def test_unknown_editor_copy_is_not_overwritten_with_local_text(self):
        with self.assertRaises(ValueError):
            complete_body('线上已有其他修改。' * 100, ['本地原稿。' * 300])
