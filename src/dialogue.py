"""Conversation processing, kept independent of native instrumentation."""
from datetime import datetime
from collections import deque
import json
from pathlib import Path


class DialogueAssembler:
    def __init__(self):
        self.reset()

    def feed(self, role, raw):
        text = bytes(raw).decode('gb18030', errors='replace')
        text = text.replace('\r\n', '\n').replace('\r', '\n').strip(' \t\n\x00')
        if role == 'speaker':
            self.speaker = text or '未知人物'
            return None
        if role != 'text' or not text:
            return None
        pair = (self.speaker, text)
        if pair == self.last_pair:
            return None
        self.last_pair = pair
        return pair

    def reset(self):
        self.speaker = '未知人物'
        self.last_pair = None
        self._identities = set()
        self._identity_order = deque()

    def feed_event(self, event):
        """消费一条包含人物与正文的原子对白，按会话/序号过滤重传。"""
        def decode(value):
            if isinstance(value, str):
                return value
            return bytes(value or b'').decode('gb18030', errors='replace')

        text = decode(event.get('text')).replace('\r\n', '\n').replace('\r', '\n').strip(' \t\n\x00')
        if not text:
            return None
        identity = (event.get('session', ''), event['sequence'])
        if identity in self._identities:
            return None
        self._identities.add(identity)
        self._identity_order.append(identity)
        if len(self._identity_order) > 4096:
            self._identities.remove(self._identity_order.popleft())
        speaker = decode(event.get('speaker')).strip(' \t\n\x00') or '未知人物'
        return {'session': identity[0], 'sequence': identity[1], 'speaker': speaker,
                'text': text, 'time': event.get('time') or datetime.now().astimezone().isoformat(timespec='milliseconds')}


class DialogueWriter:
    def __init__(self, directory, session_name=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        session_name = session_name or datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        self.text_path = directory / (session_name + '.txt')
        self.json_path = directory / (session_name + '.jsonl')
        self._text = self.text_path.open('x', encoding='utf-8', newline='\n')
        try:
            self._json = self.json_path.open('x', encoding='utf-8', newline='\n')
        except Exception:
            self._text.close()
            raise

    def write(self, speaker, text, **metadata):
        self._text.write(f'{speaker}：{text}\n\n')
        self._text.flush()
        self._json.write(json.dumps({
            'time': datetime.now().astimezone().isoformat(timespec='milliseconds'),
            'speaker': speaker, 'text': text, **metadata,
        }, ensure_ascii=False) + '\n')
        self._json.flush()

    def close(self):
        try:
            self._text.close()
        finally:
            self._json.close()
