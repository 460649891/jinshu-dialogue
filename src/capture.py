"""后台采集服务：游戏事件入队，宿主线程解码、落盘后通知界面。"""
import json
from pathlib import Path
import queue
import threading
import time
import uuid

from dialogue import DialogueAssembler, DialogueWriter
from settings import RESOURCE_ROOT, inspect_executable
from game import running_game_pid


class EventSink:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.parser = DialogueAssembler()
        self.writer = None

    def accept(self, event, deliver):
        record = self.parser.feed_event(event)
        if record is None:
            return
        if self.writer is None:
            self.writer = DialogueWriter(self.directory)
        self.writer.write(**record)
        deliver(record)

    def close(self):
        if self.writer is not None:
            self.writer.close()


class CaptureService:
    """每次启动对应一个工作线程，停止信号也能取消等待中的 Frida 调用。"""
    def __init__(self, executable, output_directory, launch_game=False):
        self.executable = executable
        self.output_directory = Path(output_directory)
        self.launch_game = launch_game

    def run(self, stop_event, on_status, on_dialogue):
        if stop_event.is_set():
            on_status('stopped', '监听已停止', {})
            return
        sink = EventSink(self.output_directory)
        session = None
        watcher = None
        device = None
        spawned_pid = None
        finished = threading.Event()
        try:
            profile = inspect_executable(self.executable)
            import frida
            events = queue.Queue(maxsize=4096)
            overflow = threading.Event()
            cancellation = frida.Cancellable()

            def watch_stop():
                while not finished.wait(0.1):
                    if stop_event.is_set():
                        cancellation.cancel()
                        return

            def enqueue(token, message):
                try:
                    events.put_nowait((token, message))
                except queue.Full:
                    overflow.set()

            watcher = threading.Thread(target=watch_stop, daemon=True, name='capture-cancel')
            watcher.start()
            code = (RESOURCE_ROOT / 'src' / 'agent.js').read_text(encoding='utf-8')
            token = None
            retry_at = 0
            launch_pending = self.launch_game
            on_status('waiting', '正在启动游戏并准备记录…' if launch_pending else '等待游戏启动…', {})
            with cancellation:
                device = frida.get_local_device()
                while not stop_event.is_set():
                    if overflow.is_set():
                        raise RuntimeError('对话事件积压过多，已停止监听。请重新开始；已保存的记录仍可使用。')
                    if session is None and time.monotonic() >= retry_at:
                        retry_at = time.monotonic() + 1
                        pid = running_game_pid(device, profile['executable'])
                        if pid is None and launch_pending:
                            # Frida starts it suspended: no first dialogue can
                            # run between process creation and script loading.
                            spawned_pid = device.spawn([profile['executable']],
                                                       cwd=str(Path(profile['executable']).parent))
                            pid = spawned_pid
                        launch_pending = False
                        if pid is not None:
                            token = uuid.uuid4().hex
                            current_token = token
                            session = device.attach(pid)
                            session.on('detached', lambda reason, crash, t=current_token:
                                       enqueue(t, {'type':'detached', 'reason':reason}))
                            script = session.create_script('globalThis.PROFILE=' + json.dumps(
                                {**profile, 'session':token}, ensure_ascii=False) + ';\n' + code)
                            script.on('message', lambda message, data, t=current_token: enqueue(t, message))
                            script.load()
                            if spawned_pid is not None:
                                device.resume(spawned_pid)
                                spawned_pid = None
                    try:
                        event_token, message = events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if event_token != token:
                        continue
                    if message.get('type') == 'detached':
                        session = None
                        on_status('waiting', '游戏已退出，等待重新连接…', {})
                        continue
                    if message.get('type') == 'error':
                        raise RuntimeError('监听脚本错误：' + message.get('description', '未知错误'))
                    payload = message.get('payload', {})
                    if payload.get('event') == 'ready':
                        on_status('connected', '已连接 · 正在等待人物对话', {})
                    elif payload.get('event') == 'dialogue':
                        sink.accept({**payload, 'session':event_token}, on_dialogue)
                        if sink.writer is not None:
                            on_status('connected', '正在记录人物对话', {
                                'text_path':str(sink.writer.text_path), 'json_path':str(sink.writer.json_path)})
            on_status('stopped', '监听已停止，记录已保存', {})
        except Exception as error:
            if stop_event.is_set():
                on_status('stopped', '监听已停止，记录已保存', {})
            else:
                message = str(error)
                if type(error).__name__ == 'PermissionDeniedError':
                    message = '无法连接游戏。请让游戏和工具使用相同权限；游戏以管理员身份启动时，工具也需如此。'
                on_status('error', message, {})
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=0.3)
            if spawned_pid is not None and device is not None:
                # Cancellation or an attach/script failure must never strand
                # the user's newly launched game in a suspended state.
                try:
                    with frida.Cancellable():
                        device.resume(spawned_pid)
                except Exception as error:
                    on_status('error', '游戏恢复运行失败，请关闭该游戏窗口后重试：' + str(error), {})
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass
            sink.close()
