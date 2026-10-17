"""游戏启动边界：校验适配版本、避免重复窗口，并保留游戏工作目录。"""
from pathlib import Path
import subprocess

from settings import inspect_executable


def running_game_pid(device, executable):
    candidates = [process for process in device.enumerate_processes()
                  if process.name.lower() == Path(executable).name.lower()]
    if len(candidates) > 1:
        raise ValueError('检测到多个游戏进程，请只保留一个金书红颜录窗口。')
    return candidates[0].pid if candidates else None


def launch_game(executable):
    """只启动游戏；组合记录入口由 CaptureService 先安装监听再恢复进程。"""
    profile = inspect_executable(executable)
    import frida
    pid = running_game_pid(frida.get_local_device(), profile['executable'])
    if pid is not None:
        return {'pid': pid, 'already_running': True}
    path = Path(profile['executable'])
    process = subprocess.Popen([str(path)], cwd=str(path.parent), shell=False)
    return {'pid': process.pid, 'already_running': False}
