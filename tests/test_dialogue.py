"""Exercise encoding, speaker pairing, redraw filtering and durable output."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dialogue import DialogueAssembler, DialogueWriter


class DialogueTests(unittest.TestCase):
    def test_pairs_actual_gbk_speaker_and_complete_text(self):
        # A wrong encoding or pairing would corrupt the copied transcript.
        parser = DialogueAssembler()
        parser.feed('speaker', bytes([181, 234, 208, 161, 182, 254]))
        result = parser.feed('text', '这句原创文字用于编码测试。'.encode('gbk'))
        self.assertEqual(('店小二', '这句原创文字用于编码测试。'), result)

    def test_filters_shadow_and_redraw_but_retains_later_repeated_dialogue(self):
        parser = DialogueAssembler()
        parser.feed('speaker', '酒客甲'.encode('gbk'))
        self.assertEqual(('酒客甲', '听说过吗？'), parser.feed('text', '听说过吗？'.encode('gbk')))
        self.assertIsNone(parser.feed('text', '听说过吗？'.encode('gbk')))
        parser.feed('speaker', '酒客乙'.encode('gbk'))
        self.assertEqual(('酒客乙', '没有。'), parser.feed('text', '没有。'.encode('gbk')))
        parser.feed('speaker', '酒客甲'.encode('gbk'))
        self.assertEqual(('酒客甲', '听说过吗？'), parser.feed('text', '听说过吗？'.encode('gbk')))

    def test_new_dialogue_session_cannot_inherit_old_speaker(self):
        parser = DialogueAssembler()
        parser.feed('speaker', '酒客甲'.encode('gbk'))
        parser.feed('text', '你好。'.encode('gbk'))
        parser.reset()
        self.assertEqual(('未知人物', '下一段。'), parser.feed('text', '下一段。'.encode('gbk')))

    def test_preserves_punctuation_repeated_characters_and_linebreaks(self):
        parser = DialogueAssembler()
        parser.feed('speaker', '旁白'.encode('gbk'))
        self.assertEqual(('旁白', '哈哈哈哈……\n“真的？”'), parser.feed('text', '哈哈哈哈……\r\n“真的？”'.encode('gbk')))
        self.assertIsNone(parser.feed('text', b'  \x00  '))

    def test_outputs_flushed_utf8_text_and_jsonl_without_ascii_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = DialogueWriter(Path(directory), session_name='sample')
            writer.write('店小二', '客官，请进。\n这里有座。')
            self.assertTrue(writer.text_path.exists(), 'Writing a dialogue must create a transcript immediately')
            self.assertEqual('店小二：客官，请进。\n这里有座。\n\n', writer.text_path.read_text(encoding='utf-8'))
            record = json.loads(writer.json_path.read_text(encoding='utf-8'))
            self.assertEqual(('店小二', '客官，请进。\n这里有座。'), (record['speaker'], record['text']))
            writer.close()


if __name__ == '__main__':
    unittest.main()
