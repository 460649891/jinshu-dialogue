"""用户设置与游戏适配配置。"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

VERSION = '0.3.1'
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else RESOURCE_ROOT
DEFAULTS = {'game_executable':'', 'include_speaker':True, 'always_on_top':False, 'window_geometry':''}


def load_settings(path):
    result = DEFAULTS.copy()
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if isinstance(data, dict):
            for key, default in DEFAULTS.items():
                if type(data.get(key)) is type(default):
                    result[key] = data[key]
    except (OSError, ValueError, TypeError):
        pass
    return result

def save_settings(path, settings):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: settings.get(key, value) for key, value in DEFAULTS.items()
             if type(settings.get(key, value)) is type(value)}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(clean, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

def inspect_executable(path, profiles=None):
    executable = Path(path)
    if executable.is_dir():
        executable = executable / 'jshyl5.exe'
    if not executable.is_file():
        raise ValueError('找不到游戏程序，请选择游戏目录中的 jshyl5.exe。')
    if profiles is None:
        profiles = [json.loads(item.read_text(encoding='utf-8')) for item in sorted((RESOURCE_ROOT / 'profiles').glob('*.json'))]
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    for profile in profiles:
        if digest == profile['sha256']:
            return {**profile, 'executable':str(executable.resolve())}
    raise ValueError('暂不支持这个游戏版本。请选择已适配的 5.60C 主程序，或提供程序 SHA-256 供后续适配。')


def writable_app_directory():
    """优先使用便携目录，目录只读时使用用户本地数据目录。"""
    for directory in (APP_ROOT, Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'JinshuDialogue'):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory):
                pass
            return directory
        except OSError:
            continue
    raise OSError('无法创建数据目录，请把软件解压到具有写入权限的文件夹。')
