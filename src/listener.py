"""可选命令行入口，与桌面界面共用采集与落盘逻辑。"""
import argparse
import json
from pathlib import Path
import sys
import threading

from capture import CaptureService
from settings import APP_ROOT, VERSION, inspect_executable, load_settings, writable_app_directory


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='实时显示并保存金书红颜录人物对白')
    parser.add_argument('--game', help='游戏目录或 jshyl5.exe 路径')
    parser.add_argument('--check', action='store_true', help='检查所选游戏是否已适配')
    parser.add_argument('--duration', type=float, default=0, help='运行秒数，0 表示持续监听')
    args = parser.parse_args()
    stop = threading.Event()
    timer = None
    failed = False
    try:
        data_directory = writable_app_directory()
        executable = args.game or load_settings(data_directory / 'settings.json')['game_executable']
        legacy = APP_ROOT / 'config.json'
        if not executable and legacy.exists():
            executable = json.loads(legacy.read_text(encoding='utf-8-sig')).get('game_directory', '')
        profile = inspect_executable(executable)
        if args.check:
            print(f'[OK] 金书 · 对话录 {VERSION} / {profile["name"]}')
            return 0
        if args.duration > 0:
            timer = threading.Timer(args.duration, stop.set)
            timer.start()
        def status(code, message, details):
            nonlocal failed
            failed = failed or code == 'error'
            print(f'[{code}] {message}', flush=True)
            if details.get('text_path'):
                print(f'记录：{details["text_path"]}', flush=True)
        CaptureService(profile['executable'], data_directory / '对话记录').run(
            stop, status, lambda record: print(f'{record["speaker"]}：{record["text"]}\n', flush=True))
        return int(failed)
    except KeyboardInterrupt:
        stop.set()
        return 0
    except Exception as error:
        print(f'[错误] {error}', file=sys.stderr)
        return 1
    finally:
        stop.set()
        if timer is not None:
            timer.cancel()


if __name__ == '__main__':
    sys.exit(main())
