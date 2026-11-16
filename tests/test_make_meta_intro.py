import unittest
from unittest.mock import patch
from workflow.make_meta import fit_intro, unique_intro, generate_intro, intro_text, INTRO_FLOORS


class IntroGenerationTests(unittest.TestCase):
    def section(self, topic, count):
        return ''.join(f'{topic}第{i}句' + '这句话分析给定材料中的具体内容' * 3 + '。' for i in range(count))

    def test_trimming_keeps_all_three_sections_substantial(self):
        gen = {k: self.section(k, 16) for k in INTRO_FLOORS}
        fit_intro(gen)
        self.assertTrue(1800 <= len(intro_text(gen)) <= 2000)
        for key, floor in INTRO_FLOORS.items():
            self.assertGreaterEqual(len(gen[key]), floor)
            self.assertTrue(gen[key].startswith(key+'第0句'))

    def test_repeated_supplement_is_removed_before_length_validation(self):
        parts = {k: self.section(k, 5) for k in INTRO_FLOORS}
        repeated = {k: value+'\n\n'+value for k,value in parts.items()}
        unique_intro(repeated)
        self.assertEqual(repeated, parts)
        with patch('workflow.make_meta.chat_json', return_value=dict(parts)):
            with self.assertRaises(ValueError):
                generate_intro('Source facts only')


if __name__ == '__main__':
    unittest.main()
