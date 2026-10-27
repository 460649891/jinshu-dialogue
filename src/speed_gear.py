"""通过已适配 GearNT 的原生接口，为当前游戏启用两倍速。"""
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

from settings import RESOURCE_ROOT


class GearError(RuntimeError):
    pass


class _Agent:
    """消息队列等待可停止；Frida exports_sync 本身不响应 Cancellable。"""
    def __init__(self, script):
        self.script = script
        self.events = queue.Queue()
        self.request_id = 0
        script.on('message', lambda message, data: self.events.put_nowait(message))

    def call(self, method, args, stop_event, deadline):
        self.request_id += 1
        request_id = self.request_id
        self._check(stop_event, deadline)
        self.script.post({'type':'gear-call', 'id':request_id, 'method':method, 'args':args})
        while True:
            self._check(stop_event, deadline)
            try:
                message = self.events.get(timeout=min(0.05, max(0.001, deadline-time.monotonic())))
            except queue.Empty:
                continue
            if message.get('type') == 'error':
                raise GearError(message.get('description', '变速接口错误'))
            payload = message.get('payload', {})
            if payload.get('event') != 'gear-reply' or payload.get('id') != request_id:
                continue
            if payload.get('error'):
                raise GearError(payload['error'])
            return payload['result']

    @staticmethod
    def _check(stop_event, deadline):
        if stop_event.is_set():
            raise GearError('已取消变速设置')
        if time.monotonic() >= deadline:
            raise GearError('变速齿轮响应超时')

    def unload(self):
        self.script.unload()


def _same_path(left, right):
    return str(left).replace('/', '\\').removeprefix('\\\\?\\').casefold() == \
           str(right).replace('/', '\\').removeprefix('\\\\?\\').casefold()


def _gear_paths(executable):
    directory = Path(executable).resolve().parent / 'biansuchilun.com'
    profile = json.loads((RESOURCE_ROOT / 'assets' / 'gearnt-0.46.json').read_text(encoding='utf-8'))
    for name, expected in profile['files'].items():
        path = directory / name
        if not path.is_file():
            raise GearError(f'找不到 {name}，请将变速齿轮放在游戏目录的 biansuchilun.com 文件夹。')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected:
            raise GearError(f'{name} 版本校验未通过，目前只适配 GearNT 0.46。')
    return directory / 'GearNT.exe', directory / 'GearNtKe.dll'


def _manager_pid(device):
    candidates = [p for p in device.enumerate_processes() if p.name.lower() == 'gearnt.exe']
    if len(candidates) > 1:
        raise GearError('检测到多个变速齿轮进程，请只保留游戏目录中的一个。')
    return candidates[0].pid if candidates else None


def _cleanup(action, frida):
    cancellation = frida.Cancellable()
    timer = threading.Timer(0.75, cancellation.cancel)
    timer.daemon = True
    timer.start()
    try:
        with cancellation:
            action()
    except Exception:
        pass
    finally:
        timer.cancel()


def enable_gear_for_game(executable, pid, game_session, device, stop_event, timeout=8.0):
    """启动或复用齿轮，按进程句柄加入游戏，再回读游戏中的倍率确认成功。"""
    if stop_event.is_set():
        raise GearError('已取消变速设置')
    gear_exe, gear_dll = _gear_paths(executable)
    code = (RESOURCE_ROOT / 'src' / 'gear_agent.js').read_text(encoding='utf-8')
    import frida
    cancellation = frida.Cancellable()
    finished = threading.Event()
    deadline = time.monotonic() + timeout
    probe = manager_session = None

    def watch():
        while not finished.wait(0.05):
            if stop_event.is_set() or time.monotonic() >= deadline:
                cancellation.cancel()
                return

    def load(session, mode, path):
        context = {'mode':mode, 'executable':str(path), 'dll_path':str(gear_dll)}
        script = session.create_script('globalThis.GEAR_CONTEXT=' + json.dumps(context, ensure_ascii=False) + ';\n' + code)
        agent = _Agent(script)
        try:
            script.load()
        except Exception:
            _cleanup(script.unload, frida)
            raise
        return agent

    watcher = threading.Thread(target=watch, daemon=True, name='gear-cancel')
    watcher.start()
    try:
        with cancellation:
            probe = load(game_session, 'game', executable)
            before = probe.call('state', [], stop_event, deadline)
            if stop_event.is_set():
                raise GearError('已取消变速设置')
            if before['loaded'] and not _same_path(before['dll_path'], gear_dll):
                raise GearError('游戏已连接其他目录的变速齿轮，请使用同一目录。')
            manager_pid = _manager_pid(device)
            if manager_pid is None:
                _Agent._check(stop_event, deadline)
                subprocess.Popen([str(gear_exe)], cwd=str(gear_exe.parent), shell=False)
                while manager_pid is None:
                    if stop_event.wait(0.05):
                        raise GearError('已取消变速设置')
                    if time.monotonic() >= deadline:
                        raise GearError('变速齿轮启动超时')
                    manager_pid = _manager_pid(device)
            manager_session = device.attach(manager_pid)
            manager_script = load(manager_session, 'manager', gear_exe)
            other_pids = [p.pid for p in device.enumerate_processes() if p.pid not in (pid, manager_pid)]
            while True:
                manager_state = manager_script.call('state', [other_pids], stop_event, deadline)
                if manager_state['loaded']:
                    break
                if stop_event.wait(0.05):
                    raise GearError('已取消变速设置')
            if manager_state['speed'] != 10 and manager_state.get('other_targets'):
                raise GearError('变速齿轮已关联其他程序，未调整共享倍率；请先在齿轮中移除其他程序。')
            if stop_event.is_set():
                raise GearError('已取消变速设置')
            manager_script.call('configure', [pid, not before['loaded'], str(executable), other_pids],
                                stop_event, deadline)
            if stop_event.is_set():
                raise GearError('已取消变速设置')
            after = probe.call('state', [], stop_event, deadline)
            if (not after['loaded'] or not _same_path(after['dll_path'], gear_dll)
                    or after['speed'] != 10):
                raise GearError('游戏两倍速校验失败，请检查变速齿轮是否正常运行。')
            return {'multiplier':2.0, 'manager_pid':manager_pid, 'attached':not before['loaded']}
    except Exception as error:
        if stop_event.is_set():
            raise GearError('已取消变速设置') from error
        if time.monotonic() >= deadline:
            raise GearError('变速齿轮响应超时') from error
        if isinstance(error, GearError):
            raise
        message = str(error).strip().splitlines()
        raise GearError(message[0] if message else '变速齿轮设置失败') from error
    finally:
        finished.set()
        watcher.join(timeout=0.2)
        if probe is not None:
            _cleanup(probe.unload, frida)
        if manager_session is not None:
            _cleanup(manager_session.detach, frida)
