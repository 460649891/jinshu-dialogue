import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class LaunchTests(unittest.TestCase):
    def test_launch_uses_validated_executable_and_working_directory(self):
        from game import launch_game
        executable = str(Path('game/jshyl5.exe').resolve())
        device = SimpleNamespace(enumerate_processes=lambda: [])
        with patch('game.inspect_executable', return_value={'executable': executable}), \
                patch.dict(sys.modules, {'frida': SimpleNamespace(get_local_device=lambda: device)}), \
                patch('game.subprocess.Popen', return_value=SimpleNamespace(pid=42)) as start:
            self.assertEqual(launch_game('chosen'), {'pid': 42, 'already_running': False})
        start.assert_called_once_with([executable], cwd=str(Path(executable).parent), shell=False)

    def test_launch_reuses_running_game_without_spawning_another(self):
        from game import launch_game
        device = SimpleNamespace(enumerate_processes=lambda: [SimpleNamespace(name='JSHYL5.EXE', pid=7)])
        with patch('game.inspect_executable', return_value={'executable':'game/jshyl5.exe'}), \
                patch.dict(sys.modules, {'frida': SimpleNamespace(get_local_device=lambda: device)}), \
                patch('game.subprocess.Popen') as start:
            self.assertEqual(launch_game('chosen'), {'pid': 7, 'already_running': True})
            start.assert_not_called()

    def test_multiple_games_are_reported_instead_of_starting_a_third(self):
        from game import running_game_pid
        device = SimpleNamespace(enumerate_processes=lambda: [
            SimpleNamespace(name='jshyl5.exe', pid=7), SimpleNamespace(name='jshyl5.exe', pid=8)])
        with self.assertRaisesRegex(ValueError, '多个游戏进程'):
            running_game_pid(device, 'game/jshyl5.exe')
