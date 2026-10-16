import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dialogue import DialogueAssembler


class NativeEventTests(unittest.TestCase):
    def test_redraw_identity_is_filtered_but_identical_next_line_is_preserved(self):
        parser = DialogueAssembler()
        event = {'session': 'first', 'sequence': 1, 'speaker': '甲', 'text': '好。'}
        self.assertIsNotNone(parser.feed_event(event))
        self.assertIsNone(parser.feed_event(event))
        self.assertIsNotNone(parser.feed_event({**event, 'sequence': 2}))

    def test_empty_name_in_atomic_event_cannot_inherit_previous_person(self):
        parser = DialogueAssembler()
        parser.feed_event({'session':'first','sequence':1,'speaker':'甲','text':'前一句。'})
        record = parser.feed_event({'session':'first','sequence':2,'speaker':'','text':'另一段。'})
        self.assertEqual('未知人物', record['speaker'])
        self.assertEqual('另一段。', record['text'])

    def test_reconnecting_session_can_restart_sequence(self):
        parser = DialogueAssembler()
        event = {'session':'first','sequence':1,'speaker':'甲','text':'好。'}
        parser.feed_event(event)
        self.assertIsNotNone(parser.feed_event({**event, 'session':'second'}))

    def test_gbk_bytes_and_name_are_decoded_together(self):
        record = DialogueAssembler().feed_event({'session':'a','sequence':1,'speaker':'乙'.encode('gbk'),'text':'哈哈哈哈……'.encode('gbk')})
        self.assertEqual(('乙','哈哈哈哈……'), (record['speaker'],record['text']))

    def test_empty_text_does_not_consume_event_identity(self):
        parser = DialogueAssembler()
        event = {'session':'first','sequence':1,'speaker':'甲','text':''}
        self.assertIsNone(parser.feed_event(event))
        self.assertIsNotNone(parser.feed_event({**event,'text':'完整正文。'}))

    def test_reset_drops_previous_identity(self):
        parser = DialogueAssembler()
        event = {'session':'first','sequence':1,'speaker':'甲','text':'好。'}
        parser.feed_event(event)
        parser.reset()
        self.assertIsNotNone(parser.feed_event(event))


if __name__ == '__main__':
    unittest.main()
