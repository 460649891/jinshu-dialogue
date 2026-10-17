"""Reader interactions; run with QT_QPA_PLATFORM=offscreen."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import QItemSelectionModel, QThread, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView


def records(count):
    return [dict(speaker=f'人物{i}', text=f'第{i}句正文。', time='20:18:00',
                 session='test', sequence=i) for i in range(count)]


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('gui'), '桌面阅读器尚未实现')
        from gui import MainWindow
        self.directory = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.directory.name) / '设置.json'
        self.window = MainWindow(settings_path=self.settings_path)
        self._slot_errors = []
        self._previous_hook = sys.excepthook
        sys.excepthook = lambda error_type, value, traceback: self._slot_errors.append(str(value))
        self.window.show()
        QTest.qWait(30)

    def tearDown(self):
        if hasattr(self, 'window'):
            self.window.close()
            self.app.processEvents()
        if hasattr(self, 'directory'):
            self.directory.cleanup()
        if hasattr(self, '_previous_hook'):
            sys.excepthook = self._previous_hook
            self.assertFalse(self._slot_errors, f'Qt 交互回调产生异常：{self._slot_errors}')

    def select_rows(self, rows):
        selection = self.window.list_view.selectionModel()
        selection.clearSelection()
        for row in rows:
            selection.select(self.window.model.index(row), QItemSelectionModel.Select)

    def test_copy_selected_uses_original_order_and_optional_speakers(self):
        self.window.append_dialogues(records(4))
        self.select_rows([3, 0, 2])
        self.window.copy_selected()
        self.assertEqual('人物0：第0句正文。\n\n人物2：第2句正文。\n\n人物3：第3句正文。', self.app.clipboard().text())
        self.window.include_speaker.setChecked(False)
        self.window.list_view.setFocus()
        QTest.keyClick(self.window.list_view, Qt.Key_C, Qt.ControlModifier)
        self.assertEqual('第0句正文。\n\n第2句正文。\n\n第3句正文。', self.app.clipboard().text())

    def test_detail_selection_keeps_native_copy_and_full_long_text(self):
        long_text = '山路向云深处延伸。\n' * 600
        self.window.append_dialogues([dict(speaker='行者', text=long_text, time='20:18:00')])
        self.window.list_view.setCurrentIndex(self.window.model.index(0))
        self.assertEqual(long_text, self.window.detail.toPlainText())
        cursor = self.window.detail.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(8, QTextCursor.KeepAnchor)
        self.window.detail.setTextCursor(cursor)
        self.window.detail.setFocus()
        QTest.keyClick(self.window.detail, Qt.Key_C, Qt.ControlModifier)
        self.assertEqual('山路向云深处延伸', self.app.clipboard().text())

    def test_new_messages_preserve_history_selection_focus_and_scroll(self):
        self.window.append_dialogues(records(80))
        QTest.qWait(30)
        self.window.list_view.setCurrentIndex(self.window.model.index(11))
        self.window.list_view.scrollTo(self.window.model.index(10), QAbstractItemView.PositionAtTop)
        self.window.list_view.setFocus()
        QTest.qWait(20)
        old_scroll = self.window.list_view.verticalScrollBar().value()
        selected = [i.row() for i in self.window.list_view.selectionModel().selectedRows()]
        self.window.append_dialogues(records(3))
        QTest.qWait(30)
        self.assertEqual(old_scroll, self.window.list_view.verticalScrollBar().value())
        self.assertEqual(selected, [i.row() for i in self.window.list_view.selectionModel().selectedRows()])
        self.assertTrue(self.window.list_view.hasFocus())
        self.assertEqual(3, self.window.unread_count)
        self.window.return_to_latest()
        QTest.qWait(20)
        bar = self.window.list_view.verticalScrollBar()
        self.assertEqual(bar.maximum(), bar.value())
        self.assertEqual(0, self.window.unread_count)
        self.window.append_dialogues(records(1))
        QTest.qWait(20)
        self.assertEqual(bar.maximum(), bar.value())

    def test_path_and_copy_preferences_survive_close(self):
        self.window.path_edit.setText('D:/游戏目录/jshyl5.exe')
        self.window.include_speaker.setChecked(False)
        self.window.close()
        saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
        self.assertEqual('D:/游戏目录/jshyl5.exe', saved['game_executable'])
        self.assertFalse(saved['include_speaker'])
        self.assertTrue(saved['window_geometry'])

    def test_empty_state_and_missing_path_give_direction(self):
        self.assertTrue(self.window.empty_state.isVisible())
        self.assertFalse(self.window.copy_selected_button.isEnabled())
        self.window.start_capture()
        self.assertIn('选择', self.window.status_message.text())
        self.assertIsNone(self.window.worker)
        self.window.append_dialogues(records(1))
        self.assertFalse(self.window.empty_state.isVisible())

    def test_narrow_window_places_detail_below_list(self):
        self.window.resize(740, 740)
        QTest.qWait(30)
        self.assertEqual(Qt.Vertical, self.window.splitter.orientation())
        self.window.resize(1180, 780)
        QTest.qWait(30)
        self.assertEqual(Qt.Horizontal, self.window.splitter.orientation())

    def test_model_caps_recent_records_without_truncating_text(self):
        from ui_model import DialogueListModel, RecordRole
        model = DialogueListModel(max_records=3)
        model.append_records(records(5))
        self.assertEqual(3, model.rowCount())
        self.assertEqual('第2句正文。', model.data(model.index(0), RecordRole)['text'])

    def test_first_batch_opens_latest_detail_and_follows_bottom(self):
        self.window.append_dialogues(records(80))
        QTest.qWait(30)
        self.assertEqual('第79句正文。', self.window.detail.toPlainText())
        bar = self.window.list_view.verticalScrollBar()
        self.assertEqual(bar.maximum(), bar.value())

    def test_bounded_history_keeps_surviving_record_at_same_position(self):
        from ui_model import RecordRole
        self.window.model.max_records = 30
        self.window.append_dialogues(records(30))
        QTest.qWait(20)
        self.window.list_view.setCurrentIndex(self.window.model.index(12))
        self.window.list_view.scrollTo(self.window.model.index(10), QAbstractItemView.PositionAtTop)
        QTest.qWait(20)
        self.window.append_dialogues([dict(speaker='新人物', text='新内容', sequence=99)])
        QTest.qWait(20)
        top = self.window.list_view.indexAt(self.window.list_view.viewport().rect().topLeft())
        self.assertEqual('第10句正文。', top.data(RecordRole)['text'])
        self.assertEqual('第12句正文。', self.window.detail.toPlainText())
        self.assertEqual('第12句正文。', self.window.list_view.currentIndex().data(RecordRole)['text'])

    def test_close_waits_for_capture_thread_and_flushes_queued_dialogue(self):
        release = threading.Event()

        class SlowStoppingCapture:
            def __init__(self, executable, output_directory, launch_game=False):
                pass

            def run(self, stop_event, on_status, on_dialogue):
                on_status('connected', '正在记录测试会话', {})
                on_dialogue(dict(speaker='测试', text='来自工作线程', time='20:18:00'))
                stop_event.wait(2)
                release.wait(2)

        executable = Path(self.directory.name) / 'jshyl5.exe'
        executable.write_bytes(b'test-placeholder')
        self.window.path_edit.setText(str(executable))
        with patch.dict(sys.modules, {'capture': SimpleNamespace(CaptureService=SlowStoppingCapture)}):
            self.window.start_capture()
            QTest.qWait(50)
            worker = self.window.worker
            self.window.close()
            self.assertTrue(self.window.isVisible())
            self.assertTrue(worker.isRunning())
            release.set()
            for _ in range(40):
                QTest.qWait(10)
                if not self.window.isVisible():
                    break
            self.assertFalse(self.window.isVisible())
            self.assertEqual('来自工作线程', self.window.model.records[-1]['text'])

    def test_chosen_path_is_saved_and_export_writes_plain_utf8(self):
        executable = Path(self.directory.name) / 'jshyl5.exe'
        executable.write_bytes(b'test-placeholder')
        output = Path(self.directory.name) / '摘录.txt'
        with patch('gui.QFileDialog.getOpenFileName', return_value=(str(executable), '')):
            self.window.choose_executable()
        self.assertEqual(str(executable), json.loads(self.settings_path.read_text(encoding='utf-8'))['game_executable'])
        self.window.append_dialogues([dict(speaker='', text='<正文>\n第二行')])
        with patch('gui.QFileDialog.getSaveFileName', return_value=(str(output), '')):
            self.window.export_text()
        self.assertEqual('未知人物：<正文>\n第二行\n', output.read_text(encoding='utf-8-sig'))

    def test_first_run_migrates_old_path_without_rewriting_old_config(self):
        import gui
        self.window.close()
        legacy = Path(self.directory.name) / 'config.json'
        original = '{"game_directory": "D:/旧游戏目录"}'
        legacy.write_text(original, encoding='utf-8')
        self.settings_path.unlink()
        with patch.object(gui, 'APP_ROOT', Path(self.directory.name)), patch.object(gui, 'writable_app_directory', return_value=Path(self.directory.name)):
            self.window = gui.MainWindow()
        self.assertEqual(str(Path('D:/旧游戏目录') / 'jshyl5.exe'), self.window.path_edit.text())
        self.assertEqual(original, legacy.read_text(encoding='utf-8'))

    def test_identical_lines_keep_the_same_history_anchor_when_oldest_is_removed(self):
        from ui_model import RecordRole
        self.window.model.max_records = 30
        self.window.append_dialogues([dict(speaker='同行者', text='走吧。', time='20:18:00') for _ in range(30)])
        QTest.qWait(20)
        self.window.list_view.scrollTo(self.window.model.index(10), QAbstractItemView.PositionAtTop)
        anchor = self.window.model.records[10]
        self.window.append_dialogues([dict(speaker='同行者', text='走吧。', time='20:18:00')])
        QTest.qWait(20)
        top = self.window.list_view.indexAt(self.window.list_view.viewport().rect().topLeft())
        self.assertIs(anchor, self.window.model.records[top.row()])

    def test_demo_never_starts_capture_or_creates_dialogue_logs(self):
        from gui import MainWindow
        self.window.close()
        self.window = MainWindow(settings_path=self.settings_path, demo=True)
        self.window.start_capture()
        self.assertIsNone(self.window.worker)
        self.assertGreater(self.window.model.rowCount(), 0)
        self.assertFalse(self.window.output_directory.exists())

    def test_readonly_application_fallback_is_visible_with_record_path_tooltip(self):
        import gui
        self.window.close()
        self.settings_path.unlink()
        base = Path(self.directory.name)
        with patch.object(gui, 'APP_ROOT', base / 'readonly-copy'), \
             patch.object(gui, 'writable_app_directory', return_value=base):
            self.window = gui.MainWindow()
        self.assertIn('应用目录不可写', self.window.status_message.text())
        self.assertIn(str(base / '对话记录'), self.window.status_message.text())
        self.assertEqual(str(base / '对话记录'), self.window.status_message.toolTip())

    def test_search_navigates_original_context_and_copies_plain_records(self):
        self.window.append_dialogues([
            dict(speaker='青衫客', text='Tea <江湖>，再见。', time='20:18:01'),
            dict(speaker='掌柜', text='路边的茶馆。', time='20:18:02'),
            dict(speaker='同行者', text='TEA 在路上。', time='20:18:03'),
        ])
        self.assertTrue(hasattr(self.window, 'search_edit'), '尚未提供对白搜索')
        self.window.search_edit.setText('tea')
        QTest.qWait(190)
        self.assertEqual(3, self.window.model.rowCount())
        self.assertEqual(0, self.window.list_view.currentIndex().row())
        self.assertIn('1 / 2', self.window.search_count.text())
        self.assertTrue(self.window.detail.extraSelections())
        self.window.search_edit.setFocus()
        QTest.keyClick(self.window.search_edit, Qt.Key_Return)
        self.assertEqual(2, self.window.list_view.currentIndex().row())
        QTest.keyClick(self.window.search_edit, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(0, self.window.list_view.currentIndex().row())
        self.window.copy_selected()
        self.assertEqual('青衫客：Tea <江湖>，再见。', self.app.clipboard().text())
        self.window.search_edit.setText('掌柜')
        QTest.qWait(190)
        self.assertEqual(1, self.window.list_view.currentIndex().row())
        self.assertFalse(self.window.detail.extraSelections())
        self.window.search_edit.setText('没有这句话')
        QTest.qWait(190)
        self.assertIn('无匹配', self.window.search_count.text())
        self.assertFalse(self.window.search_next_button.isEnabled())
        QTest.keyClick(self.window.search_edit, Qt.Key_Escape)
        self.assertEqual('', self.window.search_edit.text())
        self.assertIn('2000', self.window.search_scope.text())
        self.assertFalse(self.window.detail.extraSelections())

    def test_search_shortcuts_and_appended_rows_preserve_active_match_and_focus(self):
        self.window.append_dialogues(records(50))
        self.window.list_view.setFocus()
        QTest.keyClick(self.window.list_view, Qt.Key_F, Qt.ControlModifier)
        self.assertTrue(hasattr(self.window, 'search_edit'), '尚未提供搜索快捷键')
        self.assertTrue(self.window.search_edit.hasFocus())
        self.window.search_edit.setText('第1')
        QTest.qWait(190)
        self.assertEqual(1, self.window.list_view.currentIndex().row())
        QTest.keyClick(self.window.search_edit, Qt.Key_F3)
        self.assertEqual(10, self.window.list_view.currentIndex().row())
        QTest.keyClick(self.window.search_edit, Qt.Key_F3, Qt.ShiftModifier)
        self.assertEqual(1, self.window.list_view.currentIndex().row())
        self.window.list_view.setFocus()
        QTest.keyClick(self.window.list_view, Qt.Key_Return)
        self.assertEqual(10, self.window.list_view.currentIndex().row())
        QTest.keyClick(self.window.list_view, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(1, self.window.list_view.currentIndex().row())
        self.window.search_edit.setFocus()
        self.window.append_dialogues([dict(speaker='新人物', text='第100句新对白。')])
        QTest.qWait(190)
        self.assertEqual(1, self.window.list_view.currentIndex().row())
        self.assertTrue(self.window.search_edit.hasFocus())
        self.assertEqual('第1句正文。', self.window.detail.toPlainText())
        self.assertIn('/ 12', self.window.search_count.text())
        self.window.return_to_latest()
        self.window.append_dialogues(records(1))
        QTest.qWait(20)
        bar = self.window.list_view.verticalScrollBar()
        self.assertEqual(bar.maximum(), bar.value())

    def test_search_reindexes_after_trim_and_keeps_detail_one_record(self):
        self.window.model.max_records = 4
        self.window.append_dialogues(records(4))
        self.assertTrue(hasattr(self.window, 'search_edit'), '尚未提供对白搜索')
        self.window.search_edit.setText('正文')
        QTest.qWait(190)
        self.window.search_next_button.click()
        self.window.search_next_button.click()
        self.window.append_dialogues([dict(speaker='新人物', text='新正文', time='21:00:00')])
        QTest.qWait(190)
        self.assertEqual(1, self.window.list_view.currentIndex().row())
        self.assertEqual('人物2', self.window.detail_speaker.text())
        self.assertEqual('第2句正文。', self.window.detail.toPlainText())
        self.assertIn('2 / 4', self.window.search_count.text())
        self.window.append_dialogues([dict(speaker=f'新人{i}', text=f'新正文{i}', time=f'21:00:0{i}') for i in range(8)])
        QTest.qWait(190)
        current = self.window.list_view.currentIndex().data(int(Qt.UserRole) + 1)
        self.assertEqual(current['speaker'], self.window.detail_speaker.text())
        self.assertEqual(current['text'], self.window.detail.toPlainText())
        self.assertEqual(current['time'], self.window.detail_time.text())

    def test_new_batch_keeps_detail_selection_when_record_survives(self):
        self.window.append_dialogues(records(5))
        self.window.list_view.setCurrentIndex(self.window.model.index(1))
        cursor = self.window.detail.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(4, QTextCursor.KeepAnchor)
        self.window.detail.setTextCursor(cursor)
        self.window.detail.setFocus()
        self.window.append_dialogues(records(10))
        self.assertEqual('1句正', self.window.detail.textCursor().selectedText())
        self.assertTrue(self.window.detail.hasFocus())

    def test_game_launch_runs_in_worker_and_waits_before_window_closes(self):
        self.assertTrue(hasattr(self.window, 'launch_button'), '尚未提供启动游戏按钮')
        executable = Path(self.directory.name) / 'jshyl5.exe'
        executable.write_bytes(b'test-placeholder')
        self.window.path_edit.setText(str(executable))
        entered, release = threading.Event(), threading.Event()
        called_on = []

        def launch_game(path):
            called_on.append((path, QThread.currentThread() is self.app.thread()))
            entered.set()
            release.wait(2)
            return dict(pid=9123, already_running=False)

        with patch.dict(sys.modules, {'game': SimpleNamespace(launch_game=launch_game)}):
            self.window.launch_button.click()
            try:
                for _ in range(30):
                    QTest.qWait(10)
                    if entered.is_set():
                        break
                self.assertTrue(entered.is_set())
                self.assertEqual([(str(executable), False)], called_on)
                self.assertFalse(self.window.launch_button.isEnabled())
                self.assertFalse(self.window.launch_capture_button.isEnabled())
                self.assertFalse(self.window.start_button.isEnabled())
                self.window.launch_button.click()
                self.window.close()
                self.assertTrue(self.window.isVisible())
            finally:
                release.set()
                for _ in range(40):
                    QTest.qWait(10)
                    if not self.window.isVisible():
                        break
            self.assertFalse(self.window.isVisible())
            self.assertEqual(1, len(called_on))

    def test_combined_launch_records_once_and_waiting_capture_can_launch_game(self):
        self.assertTrue(hasattr(self.window, 'launch_capture_button'), '尚未提供启动并记录按钮')
        executable = Path(self.directory.name) / 'jshyl5.exe'
        executable.write_bytes(b'test-placeholder')
        self.window.path_edit.setText(str(executable))
        modes = []

        class WaitingCapture:
            def __init__(self, executable, output_directory, launch_game=False):
                modes.append(launch_game)

            def run(self, stop_event, on_status, on_dialogue):
                on_status('waiting', '等待游戏', {})
                stop_event.wait(2)

        def launch_game(path):
            return dict(pid=9123, already_running=True)

        with patch.dict(sys.modules, {'capture': SimpleNamespace(CaptureService=WaitingCapture),
                                      'game': SimpleNamespace(launch_game=launch_game)}):
            self.window.launch_capture_button.click()
            QTest.qWait(40)
            self.assertEqual([True], modes)
            self.assertFalse(self.window.launch_capture_button.isEnabled())
            self.window.start_capture(launch_game=True)
            self.assertEqual([True], modes)
            self.assertFalse(self.window.launch_button.isEnabled())
            self.window.stop_capture()
            for _ in range(40):
                QTest.qWait(10)
                if self.window.worker is None:
                    break
            self.assertIsNone(self.window.worker)
            self.window.start_button.click()
            QTest.qWait(40)
            self.assertEqual([True, False], modes)
            self.assertTrue(self.window.launch_button.isEnabled())
            self.window.launch_button.click()
            for _ in range(40):
                QTest.qWait(10)
                if '已在运行' in self.window.status_message.text() and self.window.launch_worker is None:
                    break
            self.assertIn('已在运行', self.window.status_message.text())
            self.window.stop_capture()
            QTest.qWait(40)

    def test_launch_failure_is_actionable_and_demo_disables_real_launch(self):
        self.assertTrue(hasattr(self.window, 'launch_button'), '尚未提供启动游戏按钮')
        executable = Path(self.directory.name) / 'jshyl5.exe'
        executable.write_bytes(b'test-placeholder')
        self.window.path_edit.setText(str(executable))

        def launch_game(path):
            raise ValueError('暂不支持这个游戏版本。请选择已适配程序。')

        with patch.dict(sys.modules, {'game': SimpleNamespace(launch_game=launch_game)}):
            self.window.launch_button.click()
            for _ in range(40):
                QTest.qWait(10)
                if '暂不支持' in self.window.status_message.text() and self.window.launch_worker is None:
                    break
            self.assertIn('暂不支持', self.window.status_message.text())
            self.assertTrue(self.window.launch_button.isEnabled())
        from gui import MainWindow
        self.window.close()
        self.window = MainWindow(settings_path=self.settings_path, demo=True)
        self.assertFalse(self.window.launch_button.isEnabled())
        self.assertFalse(self.window.launch_capture_button.isEnabled())
        self.window.launch_game()
        self.assertIsNone(self.window.launch_worker)

    def test_all_launch_actions_fit_at_700_pixels(self):
        self.assertTrue(hasattr(self.window, 'launch_button'), '尚未提供启动游戏按钮')
        self.window.resize(700, 780)
        QTest.qWait(30)
        self.assertEqual(700, self.window.width())
        self.assertGreaterEqual(self.window.detail.viewport().height(), 60)
        for button in (self.window.launch_capture_button, self.window.launch_button, self.window.start_button):
            self.assertGreaterEqual(button.width(), button.sizeHint().width())
            self.assertTrue(self.window.rect().contains(button.mapTo(self.window, button.rect().topLeft())))
            self.assertTrue(self.window.rect().contains(button.mapTo(self.window, button.rect().bottomRight())))

    def test_waiting_capture_can_retry_game_launch_after_failure(self):
        executable = Path(self.directory.name) / 'jshyl5.exe'
        executable.write_bytes(b'test-placeholder')
        self.window.path_edit.setText(str(executable))
        attempts = []

        class WaitingCapture:
            def __init__(self, executable, output_directory, launch_game=False):
                pass

            def run(self, stop_event, on_status, on_dialogue):
                on_status('waiting', '等待游戏', {})
                stop_event.wait(2)

        def launch_game(path):
            attempts.append(path)
            if len(attempts) == 1:
                raise OSError('启动失败，请重试。')
            return dict(pid=9123, already_running=False)

        with patch.dict(sys.modules, {'capture': SimpleNamespace(CaptureService=WaitingCapture),
                                      'game': SimpleNamespace(launch_game=launch_game)}):
            self.window.start_capture()
            QTest.qWait(30)
            try:
                self.window.launch_button.click()
                for _ in range(40):
                    QTest.qWait(10)
                    if self.window.launch_worker is None:
                        break
                self.assertIn('启动失败', self.window.status_message.text())
                self.assertTrue(self.window.launch_button.isEnabled())
                self.window.launch_button.click()
                for _ in range(40):
                    QTest.qWait(10)
                    if self.window.launch_worker is None:
                        break
                self.assertIn('游戏已启动', self.window.status_message.text())
                self.assertEqual(2, len(attempts))
            finally:
                self.window.stop_capture()
                QTest.qWait(40)

    def test_rapid_worker_dialogues_keep_selected_name_text_and_time_together(self):
        executable = Path(self.directory.name) / 'jshyl5.exe'
        executable.write_bytes(b'test-placeholder')
        self.window.path_edit.setText(str(executable))
        self.window.model.max_records = 30

        class BurstCapture:
            def __init__(self, executable, output_directory, launch_game=False):
                pass

            def run(self, stop_event, on_status, on_dialogue):
                on_status('connected', '正在接收对白', {})
                for sequence in range(350):
                    on_dialogue(dict(speaker=f'人物{sequence}', text=f'正文{sequence}',
                                     time=f'时刻{sequence}', sequence=sequence, session='burst'))
                stop_event.wait(2)

        with patch.dict(sys.modules, {'capture': SimpleNamespace(CaptureService=BurstCapture)}):
            self.window.start_capture()
            try:
                for _ in range(200):
                    QTest.qWait(10)
                    if self.window.model.total_received == 350:
                        break
                self.assertEqual(350, self.window.model.total_received)
                self.assertEqual(30, self.window.model.rowCount())
                self.window.list_view.setCurrentIndex(self.window.model.index(12))
                self.assertEqual('人物332', self.window.detail_speaker.text())
                self.assertEqual('正文332', self.window.detail.toPlainText())
                self.assertEqual('时刻332', self.window.detail_time.text())
                self.window.search_edit.setText('正文349')
                QTest.qWait(190)
                self.assertEqual('人物349', self.window.detail_speaker.text())
                self.assertEqual('正文349', self.window.detail.toPlainText())
                self.assertEqual('时刻349', self.window.detail_time.text())
            finally:
                self.window.stop_capture()
                QTest.qWait(40)


class SingleInstanceTests(unittest.TestCase):
    def test_separate_working_copies_share_one_lock_and_release_on_exit(self):
        import gui
        self.assertTrue(hasattr(gui, 'acquire_instance_lock'), '尚未实现跨副本单实例门禁')
        source = str(Path(__file__).resolve().parents[1] / 'src')
        script = (
            'import sys\n'
            f'sys.path.insert(0, {source!r})\n'
            'from PySide6.QtCore import QCoreApplication\n'
            'from gui import acquire_instance_lock\n'
            'app = QCoreApplication([])\n'
            'lock = acquire_instance_lock()\n'
            'print("acquired" if lock else "blocked", flush=True)\n'
            'if lock and sys.argv[1] == "hold": sys.stdin.readline()\n'
            'if lock: lock.unlock()\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            first_copy, other_copy = local / 'copy-a', local / 'copy-b'
            first_copy.mkdir()
            other_copy.mkdir()
            environment = {**os.environ, 'LOCALAPPDATA': str(local / 'shared-user-data'),
                           'PYTHONIOENCODING': 'utf-8', 'QT_QPA_PLATFORM': 'offscreen'}
            lock_path = local / 'shared-user-data' / 'JinshuDialogue' / 'desktop.lock'
            first = subprocess.Popen([sys.executable, '-c', script, 'hold'], cwd=first_copy,
                                     env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding='utf-8')
            try:
                self.assertEqual('acquired', first.stdout.readline().strip())
                self.assertTrue(lock_path.exists())
                second = subprocess.run([sys.executable, '-c', script, 'probe'], cwd=other_copy,
                                        env=environment, capture_output=True, text=True,
                                        encoding='utf-8', timeout=8)
                self.assertEqual(0, second.returncode, second.stderr)
                self.assertEqual('blocked', second.stdout.strip())
            finally:
                _, error = first.communicate('\n', timeout=8)
            self.assertEqual(0, first.returncode, error)
            self.assertFalse(lock_path.exists())
            third = subprocess.run([sys.executable, '-c', script, 'probe'], cwd=other_copy,
                                   env=environment, capture_output=True, text=True,
                                   encoding='utf-8', timeout=8)
            self.assertEqual(0, third.returncode, third.stderr)
            self.assertEqual('acquired', third.stdout.strip())
            self.assertFalse(lock_path.exists())

    def test_duplicate_start_explains_existing_window_without_constructing_another(self):
        import gui
        self.assertTrue(hasattr(gui, 'acquire_instance_lock'), '尚未实现跨副本单实例门禁')
        with patch.object(gui, 'acquire_instance_lock', return_value=None), \
             patch.object(gui.QMessageBox, 'information') as information, \
             patch.object(gui, 'MainWindow', side_effect=AssertionError('不应创建第二个窗口')):
            self.assertEqual(0, gui.main([]))
        self.assertIn('已经在运行', information.call_args.args[2])

    def test_demo_and_smoke_start_without_touching_instance_lock(self):
        import gui
        self.assertTrue(hasattr(gui, 'acquire_instance_lock'), '尚未实现跨副本单实例门禁')
        source = str(Path(__file__).resolve().parents[1] / 'src')
        with tempfile.TemporaryDirectory() as directory:
            for arguments in (['--demo', '--smoke-test'], ['--smoke-test']):
                script = (
                    'import sys\nfrom pathlib import Path\n'
                    f'sys.path.insert(0, {source!r})\n'
                    'import gui\n'
                    f'gui.writable_app_directory = lambda: Path({directory!r})\n'
                    'def forbidden_lock(): raise AssertionError("预览和自检不应申请单实例锁")\n'
                    'gui.acquire_instance_lock = forbidden_lock\n'
                    f'raise SystemExit(gui.main({arguments!r}))\n'
                )
                result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                        text=True, encoding='utf-8', timeout=8,
                                        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                             'PYTHONIOENCODING': 'utf-8'})
                self.assertEqual(0, result.returncode, result.stderr)

    def test_normal_main_releases_shared_lock_when_window_closes(self):
        source = str(Path(__file__).resolve().parents[1] / 'src')
        with tempfile.TemporaryDirectory() as directory:
            script = (
                'import sys\nfrom pathlib import Path\n'
                f'sys.path.insert(0, {source!r})\n'
                'from PySide6.QtCore import QTimer\n'
                'import gui\n'
                'original_window = gui.MainWindow\n'
                'def closing_window(**kwargs):\n'
                f'    window = original_window(settings_path=Path({directory!r}) / "settings.json")\n'
                '    QTimer.singleShot(80, window.close)\n'
                '    return window\n'
                'gui.MainWindow = closing_window\n'
                'raise SystemExit(gui.main([]))\n'
            )
            local_data = Path(directory) / 'shared-user-data'
            result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                    text=True, encoding='utf-8', timeout=8,
                                    env={**os.environ, 'LOCALAPPDATA': str(local_data),
                                         'QT_QPA_PLATFORM': 'offscreen', 'PYTHONIOENCODING': 'utf-8'})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((local_data / 'JinshuDialogue').is_dir())
            self.assertFalse((local_data / 'JinshuDialogue' / 'desktop.lock').exists())


if __name__ == '__main__':
    unittest.main()
