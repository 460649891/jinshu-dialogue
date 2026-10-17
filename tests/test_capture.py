import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class CaptureTests(unittest.TestCase):
    def _launch_capture(self, existing=False, failure=None):
        from capture import CaptureService
        stop = threading.Event()
        calls, states, delivered = [], [], []
        class Cancellation:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cancel(self): pass
        class Script:
            def on(self, name, callback): self.callback = callback
            def load(self):
                calls.append('load')
                if failure == 'cancel':
                    stop.set()
                    raise RuntimeError('cancelled during load')
                if failure == 'load': raise RuntimeError('invalid signature')
                self.callback({'type':'send', 'payload':{'event':'ready'}}, None)
                self.callback({'type':'send', 'payload':{
                    'event':'dialogue', 'sequence':1, 'speaker':'甲', 'text':'你好'}}, None)
        class Session:
            def on(self, *args): pass
            def create_script(self, code): return Script()
            def detach(self): calls.append('detach')
        class Device:
            def enumerate_processes(self):
                return [SimpleNamespace(name='jshyl5.exe', pid=42)] if existing else []
            def spawn(self, argv, cwd): calls.append('spawn'); return 42
            def attach(self, pid):
                calls.append('attach')
                if failure == 'attach': raise RuntimeError('attach failed')
                return Session()
            def resume(self, pid): calls.append('resume')
        def receive(record):
            delivered.append(record)
            stop.set()
        with tempfile.TemporaryDirectory() as root, \
                patch('capture.inspect_executable', return_value={'executable':'C:/Game/jshyl5.exe'}), \
                patch.dict(sys.modules, {'frida':SimpleNamespace(
                    Cancellable=Cancellation, get_local_device=lambda: Device())}):
            CaptureService('chosen', root, launch_game=True).run(
                stop, lambda *args: states.append(args), receive)
            if delivered:
                logs = list(Path(root).glob('*.txt'))
                self.assertEqual(len(logs), 1)
                self.assertIn('甲：你好', logs[0].read_text(encoding='utf-8'))
        return calls, states, delivered

    def test_combined_launch_installs_capture_before_game_resumes(self):
        calls, states, delivered = self._launch_capture()
        self.assertEqual(calls, ['spawn', 'attach', 'load', 'resume', 'detach'])
        self.assertEqual(delivered[0]['speaker'], '甲')
        self.assertEqual(states[-1][0], 'stopped')

    def test_combined_launch_reuses_existing_game(self):
        calls, _, delivered = self._launch_capture(existing=True)
        self.assertEqual(calls, ['attach', 'load', 'detach'])
        self.assertEqual(len(delivered), 1)

    def test_failed_or_cancelled_start_never_leaves_spawned_game_suspended(self):
        for failure in ('attach', 'load', 'cancel'):
            with self.subTest(failure=failure):
                calls, states, delivered = self._launch_capture(failure=failure)
                self.assertEqual(calls.count('resume'), 1)
                self.assertEqual(delivered, [])
                self.assertEqual(states[-1][0], 'stopped' if failure == 'cancel' else 'error')

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
