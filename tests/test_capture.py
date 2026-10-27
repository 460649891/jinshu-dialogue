import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class CaptureTests(unittest.TestCase):
    def _launch_capture(self, existing=False, failure=None, launch_game=True,
                        gear_action=None, repeat_ready=False, dialogue_count=1, reconnect=False,
                        detach_action=None, dialogue_action=None, status_action=None):
        from capture import CaptureService
        stop = threading.Event()
        calls, states, delivered = [], [], []
        session_number = 0
        sessions = []
        class Cancellation:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cancel(self): pass
        class Script:
            def __init__(self, session): self.session = session
            def on(self, name, callback): self.callback = callback
            def load(self):
                calls.append('load')
                if failure == 'cancel':
                    stop.set()
                    raise RuntimeError('cancelled during load')
                if failure == 'load': raise RuntimeError('invalid signature')
                self.callback({'type':'send', 'payload':{'event':'ready'}}, None)
                if failure == 'stop_after_ready':
                    stop.set()
                    return
                if repeat_ready:
                    self.callback({'type':'send', 'payload':{'event':'ready'}}, None)
                if failure == 'script':
                    self.callback({'type':'error', 'description':'invalid dialogue hook'}, None)
                    return
                for sequence in range(1, dialogue_count + 1):
                    self.callback({'type':'send', 'payload':{
                        'event':'dialogue', 'sequence':sequence, 'speaker':'甲',
                        'text':'你好' if sequence == 1 else '又见面'}}, None)
                if reconnect and self.session.number == 1:
                    self.session.detached('process-terminated', None)
                    self.callback({'type':'send', 'payload':{'event':'ready'}}, None)
                    self.callback({'type':'send', 'payload':{
                        'event':'dialogue', 'sequence':99, 'speaker':'旧会话', 'text':'过期事件'}}, None)
        class Session:
            def __init__(self, number): self.number = number
            def on(self, name, callback): self.detached = callback
            def create_script(self, code):
                self.script = Script(self)
                return self.script
            def detach(self):
                calls.append('detach')
                if detach_action is not None:
                    detach_action(self, sessions)
        class Device:
            def enumerate_processes(self):
                return [SimpleNamespace(name='jshyl5.exe', pid=42 + session_number)] if existing else []
            def spawn(self, argv, cwd): calls.append('spawn'); return 42
            def attach(self, pid):
                nonlocal session_number
                calls.append('attach')
                if failure == 'attach': raise RuntimeError('attach failed')
                session_number += 1
                session = Session(session_number)
                sessions.append(session)
                return session
            def resume(self, pid): calls.append('resume')
        def configure_gear(executable, pid, game_session, device, stop_event):
            calls.append('gear')
            if gear_action is not None:
                return gear_action(executable, pid, game_session, device, stop_event)
            return {'multiplier':2.0, 'manager_pid':91}
        def receive(record):
            delivered.append(record)
            if dialogue_action is not None:
                dialogue_action(record, calls)
            if len(delivered) == dialogue_count * (2 if reconnect else 1):
                stop.set()
        with tempfile.TemporaryDirectory() as root, \
                patch('capture.inspect_executable', return_value={'executable':'C:/Game/jshyl5.exe'}), \
                patch('capture.enable_gear_for_game', side_effect=configure_gear, create=True), \
                patch.dict(sys.modules, {'frida':SimpleNamespace(
                    Cancellable=Cancellation, get_local_device=lambda: Device())}):
            def status(*args):
                states.append(args)
                if status_action is not None:
                    status_action(*args, Path(root))
            CaptureService('chosen', root, launch_game=launch_game).run(stop, status, receive)
            if delivered:
                logs = list(Path(root).glob('*.txt'))
                self.assertEqual(len(logs), 1)
                saved = logs[0].read_text(encoding='utf-8')
                for record in delivered:
                    self.assertIn(f"{record['speaker']}：{record['text']}", saved)
                json_logs = list(Path(root).glob('*.jsonl'))
                self.assertEqual(len(json_logs), 1)
                self.assertEqual([json.loads(line) for line in
                                  json_logs[0].read_text(encoding='utf-8').splitlines()], delivered)
        return calls, states, delivered

    def test_combined_launch_installs_capture_before_game_resumes(self):
        calls, states, delivered = self._launch_capture()
        self.assertEqual(calls, ['spawn', 'attach', 'load', 'resume', 'gear', 'detach'])
        self.assertEqual(delivered[0]['speaker'], '甲')
        self.assertEqual(states[-1][0], 'stopped')

    def test_combined_launch_reuses_existing_game(self):
        calls, _, delivered = self._launch_capture(existing=True)
        self.assertEqual(calls, ['attach', 'load', 'gear', 'detach'])
        self.assertEqual(len(delivered), 1)

    def test_record_only_keeps_normal_speed_and_saves_dialogue(self):
        calls, states, delivered = self._launch_capture(existing=True, launch_game=False)
        self.assertEqual(len(delivered), 1)
        self.assertNotIn('gear', calls)
        connected = [state for state in states if state[0] == 'connected']
        self.assertTrue(connected)
        self.assertTrue(all('变速' not in state[1] for state in connected))
        self.assertTrue(all('speed_multiplier' not in state[2] for state in connected))

    def test_combined_launch_keeps_gear_status_on_every_saved_dialogue(self):
        calls, states, delivered = self._launch_capture(repeat_ready=True, dialogue_count=2)
        self.assertEqual(len(delivered), 2)
        self.assertEqual(calls.count('gear'), 1)
        self.assertTrue(any(code == 'waiting' and '配置' in text and '2 倍速' in text
                            for code, text, _ in states))
        connected = [state for state in states if state[0] == 'connected']
        self.assertGreaterEqual(len(connected), 3)
        for _, text, details in connected:
            self.assertIn('变速齿轮 2 倍速', text)
            self.assertEqual(details.get('speed_multiplier'), 2.0)

    def test_gear_failure_remains_visible_while_dialogues_are_saved(self):
        def unavailable(*args):
            raise RuntimeError('找不到变速齿轮')
        _, states, delivered = self._launch_capture(gear_action=unavailable, dialogue_count=2)
        self.assertEqual(len(delivered), 2)
        self.assertFalse(any(code == 'error' for code, _, _ in states))
        for code, text, details in states:
            if code == 'connected':
                self.assertIn('变速未启用：找不到变速齿轮', text)
                self.assertEqual(details.get('speed_warning'), '找不到变速齿轮')
                self.assertNotIn('speed_multiplier', details)

    def test_reconnect_configures_new_session_once_and_clears_old_speed_result(self):
        targets = []
        def configure(executable, pid, session, device, stop):
            targets.append((executable, pid, session))
            if len(targets) == 2:
                raise RuntimeError('再次设置失败')
            return {'multiplier':2.0, 'manager_pid':91}
        calls, states, delivered = self._launch_capture(
            existing=True, gear_action=configure, repeat_ready=True, reconnect=True)
        self.assertEqual(len(delivered), 2)
        self.assertNotEqual(delivered[0]['session'], delivered[1]['session'])
        self.assertEqual([target[:2] for target in targets],
                         [('C:/Game/jshyl5.exe', 42), ('C:/Game/jshyl5.exe', 43)])
        self.assertIsNot(targets[0][2], targets[1][2])
        self.assertEqual(calls.count('gear'), 2)
        recording = [state for state in states if '正在记录人物对话' in state[1]]
        self.assertIn('变速齿轮 2 倍速', recording[0][1])
        self.assertIn('变速未启用：再次设置失败', recording[1][1])
        self.assertNotIn('speed_multiplier', recording[1][2])
        disconnected = [state for state in states if '游戏已退出' in state[1]]
        self.assertEqual(disconnected[0][2], {})

    def test_stop_during_gear_does_not_report_speed_success_or_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                def stop_configuring(executable, pid, session, device, stop):
                    stop.set()
                    if fail:
                        raise RuntimeError('已取消变速')
                    return {'multiplier':2.0, 'manager_pid':91}
                calls, states, delivered = self._launch_capture(gear_action=stop_configuring)
                self.assertEqual(calls.count('gear'), 1)
                self.assertEqual(calls.count('resume'), 1)
                self.assertEqual(len(delivered), 1)
                self.assertFalse(any(code in ('error', 'connected') for code, _, _ in states))
                self.assertEqual(states[-1][0], 'stopped')

    def test_stop_detaches_then_saves_only_current_dialogues_before_final_status(self):
        from capture import DialogueWriter
        writers, finalized, delivery_after_detach = [], [], []
        attempts = []
        class TrackingWriter(DialogueWriter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                writers.append(self)
        def configure(executable, pid, session, device, stop):
            attempts.append(pid)
            if len(attempts) == 2:
                stop.set()
            return {'multiplier':2.0, 'manager_pid':91}
        def detached(session, sessions):
            sessions[0].script.callback({'type':'send', 'payload':{
                'event':'dialogue', 'sequence':50, 'speaker':'旧会话', 'text':'过期事件'}}, None)
            session.script.callback({'type':'error', 'payload':{
                'event':'dialogue', 'sequence':51, 'speaker':'错误消息', 'text':'不应保存'}}, None)
            session.script.callback({'type':'send', 'payload':{'event':'ready'}}, None)
            session.script.callback({'type':'send', 'payload':{
                'event':'dialogue', 'sequence':2, 'speaker':'乙', 'text':'停止前的最后一句'}}, None)
        def status(code, message, details, directory):
            if code == 'stopped':
                saved = [json.loads(line) for path in directory.glob('*.jsonl')
                         for line in path.read_text(encoding='utf-8').splitlines()]
                finalized.append((len(saved), all(writer._text.closed and writer._json.closed
                                                  for writer in writers)))
        with patch('capture.DialogueWriter', TrackingWriter):
            _, states, delivered = self._launch_capture(
                existing=True, reconnect=True, gear_action=configure, detach_action=detached,
                dialogue_action=lambda record, calls: delivery_after_detach.append('detach' in calls),
                status_action=status)
        self.assertEqual([record['text'] for record in delivered],
                         ['你好', '你好', '停止前的最后一句'])
        self.assertNotEqual(delivered[0]['session'], delivered[1]['session'])
        self.assertEqual(delivered[1]['session'], delivered[2]['session'])
        self.assertEqual(delivery_after_detach, [False, True, True])
        self.assertEqual(finalized, [(3, True)])
        self.assertEqual(states[-1][0], 'stopped')

    def test_queued_dialogue_write_failure_reports_error_when_stopping(self):
        def stop_configuring(executable, pid, session, device, stop):
            stop.set()
            raise RuntimeError('已取消变速')
        with patch('capture.DialogueWriter.write', side_effect=OSError('记录目录不可写')):
            _, states, delivered = self._launch_capture(gear_action=stop_configuring)
        self.assertEqual(delivered, [])
        self.assertEqual(states[-1][0], 'error')
        self.assertIn('记录目录不可写', states[-1][1])
        self.assertFalse(any(code == 'stopped' for code, _, _ in states))

    def test_stop_before_ready_does_not_enable_gear_or_report_connected(self):
        calls, states, delivered = self._launch_capture(failure='stop_after_ready')
        self.assertNotIn('gear', calls)
        self.assertEqual(delivered, [])
        self.assertFalse(any(code == 'connected' for code, _, _ in states))
        self.assertEqual(states[-1][0], 'stopped')

    def test_capture_script_errors_are_fatal_after_successful_speed_setup(self):
        _, states, delivered = self._launch_capture(failure='script')
        self.assertEqual(delivered, [])
        self.assertEqual(states[-1][0], 'error')
        self.assertIn('监听脚本错误：invalid dialogue hook', states[-1][1])
        self.assertNotIn('变速未启用', states[-1][1])

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
