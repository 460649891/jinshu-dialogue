"""Exercise encoding, speaker pairing, redraw filtering and durable output."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dialogue import DialogueAssembler, DialogueWriter


class DialogueTests(unittest.TestCase):
    def test_human_timestamp_formats_iso_and_legacy_clock_values(self):
        from dialogue import format_timestamp
        self.assertEqual('2026-10-17 20:10:30', format_timestamp('2026-10-17T20:10:30.123+08:00'))
        self.assertEqual('20:10:30', format_timestamp('2026-10-17T20:10:30.123+08:00', short=True))
        self.assertEqual('2026-10-17 20:10:30', format_timestamp('2026-10-17 20:10:30'))
        self.assertEqual('20:10:30', format_timestamp('20:10:30'))
        self.assertEqual('', format_timestamp(None))
        self.assertEqual('', format_timestamp('invalid timestamp'))

    def test_readable_filenames_keep_same_second_sessions_distinct(self):
        with tempfile.TemporaryDirectory() as directory, patch('dialogue.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 17, 20, 10, 30, 123456)
            first = DialogueWriter(directory)
            first.write('甲', '第一份。')
            first.close()
            second = DialogueWriter(directory)
            second.write('乙', '第二份。')
            second.close()
            self.assertEqual('对话记录_2026-10-17_20-10-30.txt', first.text_path.name)
            self.assertEqual('对话记录_2026-10-17_20-10-30_02.txt', second.text_path.name)
            self.assertEqual(second.text_path.stem, second.json_path.stem)
            self.assertIn('甲：第一份。', first.text_path.read_text(encoding='utf-8'))

    def test_existing_json_record_is_not_overwritten_or_left_with_empty_txt(self):
        with tempfile.TemporaryDirectory() as directory, patch('dialogue.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 17, 20, 10, 30)
            existing = Path(directory) / '对话记录_2026-10-17_20-10-30.jsonl'
            existing.write_text('原有记录', encoding='utf-8')
            writer = DialogueWriter(directory)
            writer.close()
            self.assertEqual('对话记录_2026-10-17_20-10-30_02.txt', writer.text_path.name)
            self.assertEqual('原有记录', existing.read_text(encoding='utf-8'))
            self.assertFalse(existing.with_suffix('.txt').exists())

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
