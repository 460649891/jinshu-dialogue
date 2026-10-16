import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class CaptureTests(unittest.TestCase):
    def test_stopping_before_start_does_not_read_game_or_create_logs(self):
        from capture import CaptureService
        with tempfile.TemporaryDirectory() as root:
            stop = threading.Event()
            stop.set()
            states = []
            CaptureService('missing.exe', Path(root) / 'logs').run(
                stop, lambda *args: states.append(args), self.fail)
            self.assertEqual(states[-1][0], 'stopped')
            self.assertFalse((Path(root) / 'logs').exists())

    def test_invalid_game_is_reported_without_background_exception(self):
        from capture import CaptureService
        with tempfile.TemporaryDirectory() as root:
            states = []
            CaptureService(Path(root) / 'missing.exe', Path(root) / 'logs').run(
                threading.Event(), lambda *args: states.append(args), self.fail)
            self.assertEqual(states[-1][0], 'error')
            self.assertIn('jshyl5.exe', states[-1][1])
            self.assertFalse((Path(root) / 'logs').exists())

    def test_persistence_precedes_delivery_and_keeps_event_identity(self):
        from capture import EventSink
        import json
        with tempfile.TemporaryDirectory() as root:
            delivered = []
            sink = EventSink(root)
            def deliver(record):
                saved = Path(sink.writer.json_path).read_text(encoding='utf-8')
                self.assertEqual(json.loads(saved.splitlines()[-1]), record)
                delivered.append(record)
            event = {'session':'one', 'sequence':1, 'speaker':'甲', 'text':'相同台词'}
            sink.accept(event, deliver)
            sink.accept(event, deliver)
            sink.accept({**event, 'sequence':2, 'speaker':''}, deliver)
            sink.close()
            self.assertEqual(len(delivered), 2)
            self.assertEqual(delivered[1]['speaker'], '未知人物')
            self.assertEqual(delivered[1]['sequence'], 2)


if __name__ == '__main__':
    unittest.main()
