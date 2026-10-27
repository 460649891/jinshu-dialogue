import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class Cancellation:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cancel(self): pass


class GearTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.exe = self.root / 'game' / 'jshyl5.exe'
        self.exe.parent.mkdir()
        self.exe.write_bytes(b'game-fixture')
        self.folder = self.exe.parent / 'biansuchilun.com'
        self.folder.mkdir()
        hashes = {}
        for name in ('GearNT.exe', 'GearNtKe.dll', 'Hook.dll'):
            data = name.encode('ascii')
            (self.folder / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (self.root / 'assets').mkdir()
        (self.root / 'assets' / 'gearnt-0.46.json').write_text(json.dumps({'files':hashes}), encoding='utf-8')
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'gear_agent.js').write_text('// external RPC boundary fixture', encoding='utf-8')
        self.loaded = False
        self.speed = 10
        self.override_path = None
        self.manager_running = True
        self.manager_detached = False
        self.probe_unloaded = False
        self.failure = None
        self.stop_on_probe = None
        self.stop_on_manager = None
        self.no_reply = False
        self.cancel_on_no_reply = None
        self.other_targets = []
        self.manager_ready_after = 1
        self.manager_queries = 0
        self.manager_auto_attaches_game = False
        owner = self

        class Script:
            def __init__(self, role):
                self.role = role
                self.exports_sync = self
            def load(self): pass
            def on(self, event, callback): self.callback = callback
            def post(self, message):
                if owner.no_reply and self.role == 'manager' and message['method'] == 'configure':
                    if owner.cancel_on_no_reply is not None:
                        owner.cancel_on_no_reply.set()
                    return
                payload = {'event':'gear-reply','id':message['id']}
                try:
                    payload['result'] = getattr(self, message['method'])(*message['args'])
                except Exception as error:
                    payload['error'] = str(error)
                self.callback({'type':'send','payload':payload}, None)
            def state(self, pids=None):
                stop = owner.stop_on_probe if self.role == 'game' else owner.stop_on_manager
                if stop is not None:
                    stop.set()
                if self.role == 'manager':
                    owner.manager_queries += 1
                    if owner.manager_auto_attaches_game:
                        owner.loaded = True
                return {'loaded':owner.loaded if self.role == 'game' else owner.manager_queries >= owner.manager_ready_after,
                        'dll_path':str(owner.override_path or owner.folder / 'GearNtKe.dll'),
                        'speed':owner.speed, 'other_targets':owner.other_targets}
            def configure(self, pid, attach, expected_game, other_pids=None):
                if owner.failure: raise RuntimeError(owner.failure)
                if pid != 7 or Path(expected_game) != owner.exe: raise RuntimeError('wrong target')
                if attach:
                    if owner.loaded: raise RuntimeError('duplicate injection')
                    owner.loaded = True
                return {'speed':10}
            def unload(self): owner.probe_unloaded = True
        class Session:
            def __init__(self, role): self.role = role
            def create_script(self, code): return Script(self.role)
            def detach(self): owner.manager_detached = True
        class Device:
            def enumerate_processes(self):
                return [SimpleNamespace(name='GearNT.exe',pid=9)] if owner.manager_running else []
            def attach(self, pid):
                if pid != 9: raise RuntimeError('wrong manager')
                return Session('manager')
        self.device = Device()
        self.game_session = Session('game')
        self.module_patch = patch.dict(sys.modules, {'frida':SimpleNamespace(Cancellable=Cancellation)})
        self.module_patch.start()

    def tearDown(self):
        self.module_patch.stop()
        self.directory.cleanup()

    def apply(self, stop=None, timeout=8.0):
        self.assertIsNotNone(importlib.util.find_spec('speed_gear'), 'GearNT adapter is not implemented')
        import speed_gear
        with patch.object(speed_gear, 'RESOURCE_ROOT', self.root):
            return speed_gear.enable_gear_for_game(str(self.exe), 7, self.game_session, self.device,
                                                  stop or threading.Event(), timeout=timeout)

    def test_supported_native_gear_enables_new_target_and_verifies_game(self):
        result = self.apply()
        self.assertEqual(2.0, result['multiplier'])
        self.assertTrue(self.loaded)
        self.assertTrue(self.probe_unloaded)
        self.assertTrue(self.manager_detached)

    def test_already_attached_game_is_reused_without_double_injection(self):
        self.loaded = True
        self.assertEqual(2.0, self.apply()['multiplier'])

    def test_manager_automatic_attachment_is_rechecked_before_injection(self):
        self.manager_auto_attaches_game = True
        self.assertEqual(2.0, self.apply()['multiplier'])

    def test_manager_success_is_not_enough_when_game_speed_is_wrong(self):
        self.speed = 5
        with self.assertRaisesRegex(RuntimeError, '校验|确认'):
            self.apply()
        self.assertTrue(self.manager_detached)

    def test_foreign_loaded_dll_is_rejected(self):
        self.loaded = True
        self.override_path = self.root / 'another' / 'GearNtKe.dll'
        with self.assertRaisesRegex(RuntimeError, '目录|路径'):
            self.apply()

    def test_unrecognized_binary_is_not_launched(self):
        (self.folder / 'GearNT.exe').write_bytes(b'unrecognized')
        with self.assertRaisesRegex(RuntimeError, '版本|校验'), patch('subprocess.Popen') as launch:
            self.apply()
        launch.assert_not_called()

    def test_missing_gear_is_reported_before_native_operations(self):
        (self.folder / 'GearNT.exe').unlink()
        with self.assertRaisesRegex(RuntimeError, 'GearNT.exe|找不到'):
            self.apply()

    def test_cancel_before_start_has_no_native_side_effects(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(RuntimeError, '取消|停止'):
            self.apply(stop)
        self.assertFalse(self.loaded)

    def test_native_failure_closes_probe_and_manager_connection(self):
        self.failure = 'native attach failed'
        with self.assertRaisesRegex(RuntimeError, 'native attach failed'):
            self.apply()
        self.assertTrue(self.probe_unloaded)
        self.assertTrue(self.manager_detached)

    def test_cancel_during_probe_does_not_launch_manager(self):
        stop = threading.Event()
        self.stop_on_probe = stop
        self.manager_running = False
        with patch('subprocess.Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, '取消'):
                self.apply(stop)
            launch.assert_not_called()

    def test_cancel_during_manager_query_does_not_inject_game(self):
        stop = threading.Event()
        self.stop_on_manager = stop
        with self.assertRaisesRegex(RuntimeError, '取消'):
            self.apply(stop)
        self.assertFalse(self.loaded)

    def test_unanswered_native_request_has_bounded_timeout_and_cleanup(self):
        self.no_reply = True
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, '超时'):
            self.apply(timeout=0.12)
        self.assertLess(time.monotonic()-started, 0.7)
        self.assertTrue(self.manager_detached)

    def test_stop_cancels_unanswered_request_without_waiting_for_rpc(self):
        self.no_reply = True
        stop = threading.Event()
        self.cancel_on_no_reply = stop
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, '取消'):
            self.apply(stop)
        self.assertLess(time.monotonic()-started, 0.7)

    def test_other_gear_target_is_not_changed_to_a_new_shared_rate(self):
        self.speed = 0
        self.other_targets = [99]
        with self.assertRaisesRegex(RuntimeError, '其他程序|其他进程'):
            self.apply()
        self.assertFalse(self.loaded)

    def test_missing_manager_is_started_in_its_own_directory(self):
        self.manager_running = False
        def launch(argv, cwd, shell):
            self.assertEqual([str(self.folder / 'GearNT.exe')], argv)
            self.assertEqual(str(self.folder), cwd)
            self.assertFalse(shell)
            self.manager_running = True
            return SimpleNamespace(pid=9)
        with patch('subprocess.Popen', side_effect=launch):
            self.assertEqual(2.0, self.apply()['multiplier'])

    def test_manager_pid_is_not_treated_as_dll_initialization_complete(self):
        self.manager_ready_after = 2
        self.assertEqual(2.0, self.apply()['multiplier'])
        self.assertGreaterEqual(self.manager_queries, 2)
