import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from settings import load_settings, save_settings, inspect_executable


class SettingsTests(unittest.TestCase):
    def test_absent_and_corrupt_settings_have_safe_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            self.assertEqual('', load_settings(path)['game_executable'])
            path.write_text('{broken', encoding='utf-8')
            self.assertTrue(load_settings(path)['include_speaker'])

    def test_unicode_game_path_and_copy_preference_survive_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data' / 'settings.json'
            save_settings(path, {'game_executable':'D:/游戏/jshyl5.exe', 'include_speaker':False})
            result = load_settings(path)
            self.assertEqual('D:/游戏/jshyl5.exe', result['game_executable'])
            self.assertFalse(result['include_speaker'])

    def test_invalid_setting_types_do_not_enable_options(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text(json.dumps({'always_on_top':'false', 'game_executable':123}), encoding='utf-8')
            self.assertFalse(load_settings(path)['always_on_top'])
            self.assertEqual('', load_settings(path)['game_executable'])

    def test_unknown_binary_is_rejected_and_supported_profile_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'jshyl5.exe'
            executable.write_bytes(b'example-build')
            with self.assertRaisesRegex(ValueError, '版本'):
                inspect_executable(executable, [{'sha256':'0'*64,'name':'test'}])
            profile = {'sha256':hashlib.sha256(b'example-build').hexdigest(),'name':'test'}
            self.assertEqual('test', inspect_executable(executable, [profile])['name'])


if __name__ == '__main__':
    unittest.main()
