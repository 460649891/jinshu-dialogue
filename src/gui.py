"""金书 · 对话录桌面阅读器。运行 python src/gui.py --demo 可安全预览。"""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QByteArray, QEvent, QLockFile, QModelIndex, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QShortcut, QTextBlockFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListView, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QStackedLayout, QTextEdit, QVBoxLayout, QWidget,
)

if __package__:
    from .settings import APP_ROOT, RESOURCE_ROOT, VERSION, load_settings, save_settings, writable_app_directory
    from .ui_model import DialogueDelegate, DialogueListModel, RecordRole, format_records
else:
    from settings import APP_ROOT, RESOURCE_ROOT, VERSION, load_settings, save_settings, writable_app_directory
    from ui_model import DialogueDelegate, DialogueListModel, RecordRole, format_records


class CaptureThread(QThread):
    dialogue = Signal(dict)
    status = Signal(str, str, dict)

    def __init__(self, executable, output_directory, parent=None, launch_game=False):
        super().__init__(parent)
        self.executable = executable
        self.output_directory = output_directory
        self.launch_game = launch_game
        self.stop_event = threading.Event()

    def run(self):
        try:
            if __package__:
                from .capture import CaptureService
            else:
                from capture import CaptureService
            CaptureService(self.executable, self.output_directory, launch_game=self.launch_game).run(
                self.stop_event, self.status.emit, self.dialogue.emit)
        except PermissionError:
            self.status.emit('error', '访问被拒绝。请将游戏与对话录以相同权限运行，再重试。', {})
        except Exception as error:
            self.status.emit('error', str(error) or '连接失败，请检查游戏路径后重试。', {})


class LaunchThread(QThread):
    launched = Signal(dict)
    failed = Signal(str)

    def __init__(self, executable, parent=None):
        super().__init__(parent)
        self.executable = executable

    def run(self):
        try:
            if __package__:
                from .game import launch_game
            else:
                from game import launch_game
            self.launched.emit(launch_game(self.executable))
        except PermissionError:
            self.failed.emit('访问被拒绝。请将游戏与对话录以相同权限运行，再重试。')
        except Exception as error:
            self.failed.emit(str(error) or '无法启动游戏，请检查所选程序后重试。')


class MainWindow(QMainWindow):
    def __init__(self, settings_path=None, demo=False):
        super().__init__()
        self.demo = demo
        self.worker = None
        self.launch_worker = None
        self._capture_launching = False
        self._capture_status_code = 'stopped'
        self.unread_count = 0
        self._following = True
        self._updating = False
        self._closing = False
        self._pending = []
        self._search_query = ''
        self._search_matches = []
        self._search_position = -1
        self._search_record = None
        self._search_total = 0
        self._search_base = 0
        self._detail_record = None
        self._last_status = 'stopped'
        base = Path(settings_path).parent if settings_path else writable_app_directory()
        self.settings_path = Path(settings_path) if settings_path else base / 'settings.json'
        self.output_directory = base / '对话记录'
        self._using_fallback_directory = settings_path is None and base.resolve() != Path(APP_ROOT).resolve()
        self.settings = load_settings(self.settings_path)
        if not settings_path and not self.settings_path.exists():
            self._migrate_legacy_path()
        self.setWindowTitle(f'金书 · 对话录  {VERSION}' + ('  ·  演示' if demo else ''))
        self.setMinimumSize(700, 660)
        self.resize(1160, 800)
        icon = RESOURCE_ROOT / 'assets' / 'app.svg'
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.model = DialogueListModel(self)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self._refresh_search)
        self._build_ui()
        theme = RESOURCE_ROOT / 'src' / 'theme.qss'
        if theme.exists():
            self.setStyleSheet(theme.read_text(encoding='utf-8'))
        geometry = self.settings.get('window_geometry')
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode('ascii', errors='ignore')))
        if self.settings['always_on_top']:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.batch_timer = QTimer(self)
        self.batch_timer.setInterval(100)
        self.batch_timer.timeout.connect(self._flush_pending)
        self.batch_timer.start()
        if demo:
            self._set_status('demo', '原创示例，仅供界面预览。未连接游戏，也不会生成对白日志。')
            self.append_dialogues(self._demo_records())
            self.list_view.setCurrentIndex(self.model.index(1))
            QTimer.singleShot(0, lambda: self.list_view.scrollToTop())
            self._update_capture_controls()
        else:
            message = '选择游戏中的 jshyl5.exe，点击“启动游戏并开始记录”。游戏已运行时也可直接开始记录。'
            if self._using_fallback_directory:
                message += f'\n应用目录不可写，记录保存于 {self.output_directory}'
            self._set_status('stopped', message)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName('appRoot')
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(16)

        header = QHBoxLayout()
        mark = QLabel('录')
        mark.setObjectName('brandMark')
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(44, 44)
        header.addWidget(mark)
        brand = QVBoxLayout()
        brand.setSpacing(2)
        title = QLabel('金书 · 对话录')
        title.setObjectName('brandTitle')
        subtitle = QLabel('留住江湖中的每一句话')
        subtitle.setObjectName('muted')
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        self.status_badge = QLabel('尚未连接')
        self.status_badge.setObjectName('statusBadge')
        header.addWidget(self.status_badge)
        version = QLabel(f'v{VERSION}')
        version.setObjectName('version')
        header.addWidget(version)
        header.setSpacing(12)
        layout.addLayout(header)

        connection = QFrame()
        connection.setObjectName('connectionPanel')
        connection_layout = QVBoxLayout(connection)
        connection_layout.setContentsMargins(16, 12, 16, 12)
        connection_layout.setSpacing(8)
        path_label = QLabel('游戏程序')
        path_label.setObjectName('fieldLabel')
        connection_layout.addWidget(path_label)
        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        self.path_edit = QLineEdit(self.settings['game_executable'])
        self.path_edit.setPlaceholderText('选择游戏目录中的 jshyl5.exe')
        self.path_edit.setAccessibleName('游戏程序路径')
        self.path_edit.setClearButtonEnabled(True)
        self.path_edit.editingFinished.connect(self._save_preferences)
        self.browse_button = QPushButton('选择程序…')
        self.browse_button.clicked.connect(self.choose_executable)
        self.start_button = QPushButton('开始记录')
        self.start_button.setMinimumWidth(108)
        self.start_button.clicked.connect(self._toggle_capture)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)
        connection_layout.addLayout(path_row)
        launch_row = QHBoxLayout()
        launch_row.setSpacing(10)
        self.launch_capture_button = QPushButton('启动游戏并开始记录')
        self.launch_capture_button.setObjectName('primaryButton')
        self.launch_capture_button.clicked.connect(lambda: self.start_capture(launch_game=True))
        self.launch_button = QPushButton('启动游戏')
        self.launch_button.clicked.connect(self.launch_game)
        launch_row.addWidget(self.launch_capture_button)
        launch_row.addWidget(self.launch_button)
        launch_row.addWidget(self.start_button)
        launch_row.addStretch()
        connection_layout.addLayout(launch_row)
        self.status_message = QLabel()
        self.status_message.setObjectName('statusMessage')
        self.status_message.setWordWrap(True)
        self.status_message.setTextFormat(Qt.PlainText)
        connection_layout.addWidget(self.status_message)
        layout.addWidget(connection)

        search_layout = QVBoxLayout()
        search_layout.setSpacing(5)
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_label = QLabel('查找对白')
        search_label.setObjectName('fieldLabel')
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('人物或正文 · Ctrl+F')
        self.search_edit.setAccessibleName('搜索人物或对白')
        search_label.setBuddy(self.search_edit)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._search_changed)
        self.search_edit.installEventFilter(self)
        self.search_previous_button = QPushButton('上一条')
        self.search_previous_button.setToolTip('Shift+Enter / Shift+F3')
        self.search_previous_button.clicked.connect(lambda: self._navigate_search(-1))
        self.search_next_button = QPushButton('下一条')
        self.search_next_button.setToolTip('Enter / F3')
        self.search_next_button.clicked.connect(lambda: self._navigate_search(1))
        self.search_previous_button.setEnabled(False)
        self.search_next_button.setEnabled(False)
        self.search_count = QLabel('输入关键词')
        self.search_count.setObjectName('muted')
        self.search_count.setMinimumWidth(86)
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_previous_button)
        search_row.addWidget(self.search_next_button)
        search_row.addWidget(self.search_count)
        search_layout.addLayout(search_row)
        self.search_scope = QLabel('搜索范围：当前界面最近 2000 条；定位原列表，保留上下文。Esc 清除')
        self.search_scope.setObjectName('muted')
        self.search_scope.setWordWrap(True)
        search_layout.addWidget(self.search_scope)
        layout.addLayout(search_layout)
        for sequence, callback in [('Ctrl+F', self._focus_search), ('F3', lambda: self._navigate_search(1)),
                                   ('Shift+F3', lambda: self._navigate_search(-1)), ('Esc', self.search_edit.clear)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        list_panel = QFrame()
        list_panel.setObjectName('readerPanel')
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        list_header = QWidget()
        list_header_layout = QHBoxLayout(list_header)
        list_header_layout.setContentsMargins(18, 13, 18, 13)
        list_title = QLabel('对白')
        list_title.setObjectName('panelTitle')
        self.count_label = QLabel('暂无记录')
        self.count_label.setObjectName('muted')
        list_header_layout.addWidget(list_title)
        list_header_layout.addStretch()
        list_header_layout.addWidget(self.count_label)
        list_layout.addWidget(list_header)
        body = QWidget()
        self.list_stack = QStackedLayout(body)
        self.list_stack.setContentsMargins(0, 0, 0, 0)
        self.list_view = QListView()
        self.list_view.setObjectName('dialogueList')
        self.list_view.setAccessibleName('对话列表，可按 Ctrl 多选，按 Ctrl+C 复制')
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(DialogueDelegate(self.list_view))
        self.list_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setMouseTracking(True)
        self.list_view.installEventFilter(self)
        self.list_view.selectionModel().currentChanged.connect(self._show_detail)
        self.list_view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.list_view.verticalScrollBar().valueChanged.connect(self._scroll_changed)
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.addStretch()
        empty_title = QLabel('江湖待续')
        empty_title.setObjectName('emptyTitle')
        empty_title.setAlignment(Qt.AlignCenter)
        empty_caption = QLabel('开始记录后，新的对白会出现在这里。\n翻阅旧对白时，仍会继续接收新内容。')
        empty_caption.setObjectName('emptyCaption')
        empty_caption.setWordWrap(True)
        empty_caption.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_layout.addSpacing(10)
        empty_layout.addWidget(empty_caption)
        empty_layout.addStretch()
        self.list_stack.addWidget(self.empty_state)
        self.list_stack.addWidget(self.list_view)
        list_layout.addWidget(body, 1)

        detail_panel = QFrame()
        detail_panel.setObjectName('readerPanel')
        detail_layout = QVBoxLayout(detail_panel)
        self.detail_layout = detail_layout
        detail_layout.setContentsMargins(22, 15, 22, 18)
        detail_layout.setSpacing(10)
        self.detail_header = QWidget()
        detail_header = QHBoxLayout(self.detail_header)
        detail_header.setContentsMargins(0, 0, 0, 0)
        detail_title = QLabel('完整正文')
        detail_title.setObjectName('panelTitle')
        detail_header.addWidget(detail_title)
        detail_header.addStretch()
        detail_hint = QLabel('选中文字可直接复制')
        detail_hint.setObjectName('muted')
        detail_header.addWidget(detail_hint)
        detail_layout.addWidget(self.detail_header)
        self.detail_speaker = QLabel('从左侧选择一条对白')
        self.detail_speaker.setObjectName('detailSpeaker')
        self.detail_speaker.setTextFormat(Qt.PlainText)
        self.detail_speaker.setWordWrap(True)
        detail_layout.addWidget(self.detail_speaker)
        self.detail_time = QLabel('人物与时间会显示在这里')
        self.detail_time.setObjectName('muted')
        self.detail_time.setTextFormat(Qt.PlainText)
        detail_layout.addWidget(self.detail_time)
        self.detail = QTextEdit()
        self.detail.setObjectName('detailText')
        self.detail.setReadOnly(True)
        self.detail.setAcceptRichText(False)
        self.detail.setPlaceholderText('完整对白将在这里展开。\n\n可以选中任意文字，按 Ctrl+C 复制。')
        self.detail.setAccessibleName('可选择复制的完整对白正文')
        self.detail.installEventFilter(self)
        self.detail.setFrameShape(QFrame.NoFrame)
        self.detail.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        detail_layout.addWidget(self.detail, 1)
        self.splitter.addWidget(list_panel)
        self.splitter.addWidget(detail_panel)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        self.splitter.setSizes([410, 620])
        layout.addWidget(self.splitter, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.copy_selected_button = QPushButton('复制选中')
        self.copy_selected_button.setObjectName('copyButton')
        self.copy_selected_button.setEnabled(False)
        self.copy_selected_button.clicked.connect(self.copy_selected)
        self.copy_all_button = QPushButton('复制全部')
        self.copy_all_button.setEnabled(False)
        self.copy_all_button.setToolTip('复制界面保留的近期对白；完整记录请打开记录文件夹。')
        self.copy_all_button.clicked.connect(self.copy_all)
        self.include_speaker = QCheckBox('包含人物名')
        self.include_speaker.setChecked(self.settings['include_speaker'])
        self.include_speaker.toggled.connect(self._save_preferences)
        self.latest_button = QPushButton('已在最新')
        self.latest_button.setObjectName('latestButton')
        self.latest_button.setEnabled(False)
        self.latest_button.clicked.connect(self.return_to_latest)
        actions.addWidget(self.copy_selected_button)
        actions.addWidget(self.copy_all_button)
        actions.addWidget(self.include_speaker)
        actions.addStretch()
        actions.addWidget(self.latest_button)
        layout.addLayout(actions)
        utility = QHBoxLayout()
        utility.setSpacing(12)
        self.export_button = QPushButton('导出 TXT…')
        self.export_button.setObjectName('quietButton')
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_text)
        folder_button = QPushButton('记录文件夹')
        folder_button.setObjectName('quietButton')
        folder_button.clicked.connect(self.open_record_folder)
        self.always_on_top = QCheckBox('窗口置顶')
        self.always_on_top.setChecked(self.settings['always_on_top'])
        self.always_on_top.toggled.connect(self._toggle_on_top)
        self.feedback = QLabel('Ctrl 多选  /  Shift 连选  /  Ctrl+C 复制')
        self.feedback.setObjectName('muted')
        utility.addWidget(self.export_button)
        utility.addWidget(folder_button)
        utility.addWidget(self.always_on_top)
        utility.addStretch()
        utility.addWidget(self.feedback)
        layout.addLayout(utility)

    def _migrate_legacy_path(self):
        try:
            old = json.loads((APP_ROOT / 'config.json').read_text(encoding='utf-8-sig'))
            directory = old.get('game_directory')
            if isinstance(directory, str) and directory:
                self.settings['game_executable'] = str(Path(directory) / 'jshyl5.exe')
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def append_dialogues(self, records):
        if not records:
            return
        following = self._following and not self.search_edit.text().strip()
        bar = self.list_view.verticalScrollBar()
        old_scroll = bar.value()
        anchor = self.list_view.indexAt(self.list_view.viewport().rect().topLeft())
        anchor_record = self.model.records[anchor.row()] if anchor.isValid() else None
        anchor_top = self.list_view.visualRect(anchor).top() if anchor.isValid() else 0
        self._updating = True
        count = self.model.append_records(records)
        if not count:
            self._updating = False
            return
        self.list_stack.setCurrentWidget(self.list_view)
        self.list_view.doItemsLayout()
        anchor_row = next((row for row, record in enumerate(self.model.records) if record is anchor_record), None)
        if following:
            self.list_view.scrollToBottom()
        elif anchor_row is not None:
            self.list_view.scrollTo(self.model.index(anchor_row), QAbstractItemView.PositionAtTop)
            bar.setValue(bar.value() - anchor_top)
        else:
            bar.setValue(old_scroll)
        if not following:
            self.unread_count += count
        if self.model.rowCount() == count and not self.list_view.currentIndex().isValid():
            self.list_view.setCurrentIndex(self.model.index(self.model.rowCount() - 1))
        self._updating = False
        self._show_detail(self.list_view.currentIndex())
        self._selection_changed()
        self.count_label.setText(f'{self.model.rowCount():,} 条' if self.model.total_received <= self.model.max_records
                                 else f'最近 {self.model.rowCount():,} 条')
        self.copy_all_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self._update_latest()
        if self.search_edit.text().strip() and not self.search_timer.isActive():
            self.search_timer.start()

    def _scroll_changed(self, value):
        if self._updating:
            return
        bar = self.list_view.verticalScrollBar()
        self._following = not self.search_edit.text().strip() and value >= bar.maximum() - 3
        if self._following:
            self.unread_count = 0
        self._update_latest()

    def _update_latest(self):
        if self.unread_count:
            self.latest_button.setText(f'新增 {self.unread_count} 条 · 回到最新')
        else:
            self.latest_button.setText('已在最新' if self._following else '回到最新')
        self.latest_button.setEnabled(not self._following or self.unread_count > 0)

    def return_to_latest(self):
        self.search_edit.clear()
        self._updating = True
        self.list_view.scrollToBottom()
        self._following = True
        self.unread_count = 0
        self._updating = False
        self._update_latest()

    def _show_detail(self, current, previous=QModelIndex()):
        if self._updating:
            return
        # QVariant 会复制 dict；直接使用模型中的同一条记录以保留正文选区。
        record = self.model.records[current.row()] if current.isValid() and 0 <= current.row() < self.model.rowCount() else None
        if record is self._detail_record:
            return
        self._detail_record = record
        if record:
            self.detail_speaker.setText(record['speaker'])
            self.detail_time.setText(record['time'] or '未提供时间')
            self.detail.setPlainText(record['text'])
            cursor = self.detail.textCursor()
            cursor.select(QTextCursor.Document)
            paragraph = QTextBlockFormat()
            paragraph.setLineHeight(150, QTextBlockFormat.ProportionalHeight.value)
            cursor.mergeBlockFormat(paragraph)
        else:
            self.detail_speaker.setText('从左侧选择一条对白')
            self.detail_time.setText('人物与时间会显示在这里')
            self.detail.clear()
        self._highlight_search()

    def _focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _search_changed(self, text):
        if text.strip():
            self._following = False
            self._update_latest()
            self.search_count.setText('正在查找…')
            self.search_timer.start()
        else:
            self.search_timer.stop()
            self._search_query = ''
            self._search_matches = []
            self._search_position = -1
            self._search_record = None
            self._update_search_feedback()
            self._highlight_search()

    def _refresh_search(self):
        query = self.search_edit.text().strip().casefold()
        if not query:
            return
        changed = query != self._search_query
        base = self.model.total_received - self.model.rowCount()
        if changed:
            self._search_matches = self.model.search_rows(query)
        else:
            removed = base - self._search_base
            self._search_matches = [row - removed for row in self._search_matches if row >= removed]
            self._search_matches.extend(self.model.search_rows(query, self._search_total - base))
        self._search_query = query
        self._search_total = self.model.total_received
        self._search_base = base
        old_position = self._search_position
        self._search_position = next((position for position, row in enumerate(self._search_matches)
                                      if self.model.records[row] is self._search_record), -1)
        if self._search_matches and (changed or self._search_position < 0):
            self._search_position = 0 if changed else min(max(0, old_position), len(self._search_matches) - 1)
            self._select_search_match()
        elif not self._search_matches:
            self._search_record = None
        self._update_search_feedback()
        self._highlight_search()

    def _update_search_feedback(self):
        count = len(self._search_matches)
        self.search_count.setText(f'{self._search_position + 1} / {count}' if count else
                                  '无匹配' if self.search_edit.text().strip() else '输入关键词')
        self.search_previous_button.setEnabled(count > 0)
        self.search_next_button.setEnabled(count > 0)

    def _navigate_search(self, direction):
        if self.search_timer.isActive():
            self.search_timer.stop()
            changed = self.search_edit.text().strip().casefold() != self._search_query
            self._refresh_search()
            if changed:
                return
        if not self._search_matches:
            return
        self._search_position = (self._search_position + direction) % len(self._search_matches)
        self._select_search_match()
        self._update_search_feedback()

    def _select_search_match(self):
        row = self._search_matches[self._search_position]
        self._search_record = self.model.records[row]
        self._updating = True
        self.list_view.setCurrentIndex(self.model.index(row))
        self.list_view.scrollTo(self.model.index(row), QAbstractItemView.PositionAtCenter)
        self._updating = False
        self._following = False
        self._show_detail(self.list_view.currentIndex())
        self._update_latest()

    def _highlight_search(self):
        selections = []
        query = self.search_edit.text().strip()
        if query:
            cursor = self.detail.document().find(query)
            while not cursor.isNull():
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format.setBackground(QColor('#66532b'))
                selection.format.setForeground(QColor('#fff2c6'))
                selections.append(selection)
                cursor = self.detail.document().find(query, cursor)
        self.detail.setExtraSelections(selections)

    def _selection_changed(self, *args):
        count = len(self.list_view.selectionModel().selectedRows())
        self.copy_selected_button.setEnabled(count > 0)
        self.copy_selected_button.setText(f'复制选中 {count} 条' if count else '复制选中')

    def _copy_records(self, records):
        if records:
            QApplication.clipboard().setText(format_records(records, self.include_speaker.isChecked()))
            self.feedback.setText(f'已复制 {len(records)} 条对白')
            QTimer.singleShot(3500, lambda: self.feedback.setText('Ctrl 多选  /  Shift 连选  /  Ctrl+C 复制'))

    def copy_selected(self):
        rows = sorted(index.row() for index in self.list_view.selectionModel().selectedRows())
        self._copy_records([self.model.records[row] for row in rows])

    def copy_all(self):
        self._copy_records(self.model.records)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            if (event.key() in (Qt.Key_Return, Qt.Key_Enter) and
                    watched in (self.search_edit, self.list_view, self.detail) and self.search_edit.text().strip()):
                self._navigate_search(-1 if event.modifiers() & Qt.ShiftModifier else 1)
                return True
        if event.type() == QEvent.KeyPress and watched is self.list_view and event.matches(QKeySequence.Copy):
            self.copy_selected()
            return True
        return super().eventFilter(watched, event)

    def choose_executable(self):
        filename, _ = QFileDialog.getOpenFileName(self, '选择金书红颜录游戏程序', self.path_edit.text(),
                                                '金书红颜录 (jshyl5.exe);;可执行程序 (*.exe)')
        if filename:
            self.path_edit.setText(filename)
            self._save_preferences()

    def _toggle_capture(self):
        if self.worker and self.worker.isRunning():
            self.stop_capture()
        else:
            self.start_capture()

    def start_capture(self, launch_game=False):
        if self.demo or self.worker is not None or self.launch_worker is not None or self._closing:
            return
        filename = self.path_edit.text().strip()
        if not filename or not Path(filename).is_file():
            self._set_status('error', '找不到游戏程序，请选择游戏目录中的 jshyl5.exe。')
            return
        self._save_preferences()
        self._capture_launching = launch_game
        self._capture_status_code = 'waiting'
        self._set_status('waiting', '正在启动游戏并准备记录，请稍候…' if launch_game else
                         '正在等待游戏。可点击“启动游戏”，运行后会自动连接。')
        self.worker = CaptureThread(filename, self.output_directory, self, launch_game=launch_game)
        self.worker.dialogue.connect(self._enqueue_dialogue)
        self.worker.status.connect(self._capture_status)
        self.worker.finished.connect(self._worker_finished)
        self.start_button.setText('停止记录')
        self._update_capture_controls()
        self.worker.start()

    def stop_capture(self):
        if self.worker:
            self.worker.stop_event.set()
            self.start_button.setText('正在停止…')
            self._update_capture_controls()

    def launch_game(self):
        if (self.demo or self.launch_worker is not None or self._capture_launching or self._closing or
                (self.worker is not None and (self._capture_status_code != 'waiting' or self.worker.stop_event.is_set()))):
            return
        filename = self.path_edit.text().strip()
        if not filename or not Path(filename).is_file():
            self._set_status('error', '找不到游戏程序，请选择游戏目录中的 jshyl5.exe。')
            return
        self._save_preferences()
        self._set_status('waiting' if self.worker else 'launching', '正在启动游戏，请稍候…')
        self.launch_worker = LaunchThread(filename, self)
        self.launch_worker.launched.connect(self._game_launched)
        self.launch_worker.failed.connect(lambda message: self._set_status('error', message))
        self.launch_worker.finished.connect(self._launch_finished)
        self.launch_button.setText('正在启动…')
        self._update_capture_controls()
        self.launch_worker.start()

    def _game_launched(self, result):
        message = '游戏已在运行' if result['already_running'] else '游戏已启动'
        message += f"（PID {result['pid']}）。"
        message += '正在等待自动连接。' if self.worker and self._capture_status_code == 'waiting' else \
                   '正在记录对白。' if self.worker and self._capture_status_code == 'connected' else '点击“开始记录”即可接收对白。'
        self._set_status(self._capture_status_code if self.worker else 'stopped', message)

    def _launch_finished(self):
        finished, self.launch_worker = self.launch_worker, None
        self.launch_button.setText('启动游戏')
        self._update_capture_controls()
        if finished:
            finished.deleteLater()
        self._close_when_workers_finish()

    def _update_capture_controls(self):
        capturing = self.worker is not None
        launching = self.launch_worker is not None
        available = not self.demo and not self._closing
        self.path_edit.setEnabled(not capturing and not launching and not self._closing)
        self.browse_button.setEnabled(not capturing and not launching and not self._closing)
        self.launch_capture_button.setEnabled(available and not capturing and not launching)
        self.launch_button.setEnabled(available and not launching and not self._capture_launching and
                                      (not capturing or (self._capture_status_code == 'waiting' and not self.worker.stop_event.is_set())))
        self.start_button.setEnabled(available and (not launching or capturing) and
                                     (not capturing or not self.worker.stop_event.is_set()))

    def _close_when_workers_finish(self):
        if self._closing and self.worker is None and self.launch_worker is None:
            QTimer.singleShot(0, self.close)

    def _enqueue_dialogue(self, record):
        self._pending.append(record)

    def _flush_pending(self):
        if self._pending:
            records, self._pending = self._pending, []
            self.append_dialogues(records)

    def _capture_status(self, code, message, details):
        self._capture_status_code = code
        if code in ('connected', 'error', 'stopped'):
            self._capture_launching = False
        text_path = details.get('text_path')
        if text_path:
            self.output_directory = Path(text_path).parent
        self._set_status(code, message)
        self._update_capture_controls()

    def _set_status(self, code, message):
        self._last_status = code
        titles = {'waiting': '等待游戏', 'connected': '正在记录', 'error': '需要处理',
                  'stopped': '尚未连接', 'demo': '演示模式', 'launching': '正在启动'}
        self.status_badge.setText(titles.get(code, code))
        self.status_badge.setProperty('state', code)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.status_message.setText(message)
        self.status_message.setToolTip('' if self.demo else str(self.output_directory))
        self.status_message.setProperty('error', code == 'error')
        self.status_message.style().unpolish(self.status_message)
        self.status_message.style().polish(self.status_message)

    def _worker_finished(self):
        finished = self.worker
        self.worker = None
        self._capture_launching = False
        self._capture_status_code = 'stopped'
        self._flush_pending()
        self.start_button.setText('开始记录')
        self._update_capture_controls()
        if self._last_status != 'error':
            self._set_status('stopped', '记录已停止。已有对白和记录文件仍然保留。')
        if finished:
            finished.deleteLater()
        self._close_when_workers_finish()

    def export_text(self):
        if not self.model.records:
            return
        filename, _ = QFileDialog.getSaveFileName(self, '导出当前界面的对白',
                                                str(self.output_directory / '对白摘录.txt'), '文本文件 (*.txt)')
        if filename:
            try:
                Path(filename).write_text(format_records(self.model.records, self.include_speaker.isChecked()) + '\n', encoding='utf-8-sig')
                self.feedback.setText(f'已导出 {self.model.rowCount()} 条对白')
            except OSError as error:
                self._set_status('error', f'无法导出：{error}。请选择可写入的文件夹。')

    def open_record_folder(self):
        try:
            self.output_directory.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_directory)))
        except OSError as error:
            self._set_status('error', f'无法打开记录文件夹：{error}')

    def _save_preferences(self, *args):
        self.settings.update(game_executable=self.path_edit.text().strip(),
                             include_speaker=self.include_speaker.isChecked(),
                             always_on_top=self.always_on_top.isChecked(),
                             window_geometry=bytes(self.saveGeometry().toBase64()).decode('ascii'))
        try:
            save_settings(self.settings_path, self.settings)
        except OSError:
            self.feedback.setText('设置未能保存，请将软件解压到可写入的文件夹')

    def _toggle_on_top(self, checked):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()
        self._save_preferences()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'splitter'):
            compact = self.width() < 940
            orientation = Qt.Vertical if compact else Qt.Horizontal
            if self.splitter.orientation() != orientation:
                self.splitter.setOrientation(orientation)
                self.splitter.setSizes([280, 320] if orientation == Qt.Vertical else [410, 620])
            self.detail_header.setVisible(not compact)
            self.detail_layout.setContentsMargins(*(18, 12, 18, 12) if compact else (22, 15, 22, 18))
            self.detail_layout.setSpacing(6 if compact else 10)
            if self.detail_speaker.property('compact') != compact:
                self.detail_speaker.setProperty('compact', compact)
                self.detail_speaker.style().unpolish(self.detail_speaker)
                self.detail_speaker.style().polish(self.detail_speaker)
            if hasattr(self, 'feedback'):
                self.feedback.setVisible(self.width() >= 960)

    def closeEvent(self, event):
        self._save_preferences()
        if self.worker is not None or self.launch_worker is not None:
            self._closing = True
            self.stop_capture()
            self._update_capture_controls()
            self._set_status('waiting', '正在等待后台任务结束并保存记录，完成后窗口会自动关闭。')
            event.ignore()
            return
        self._flush_pending()
        event.accept()

    @staticmethod
    def _demo_records():
        lines = [
            ('客栈掌柜', '雨还没停，少侠不妨再坐一会儿。炉上的茶，正是今年的新叶。'),
            ('青衫客', '江湖路远，难得有一盏热茶。\n\n待天色放晴，我还要沿着溪水去寻那座旧桥。'),
            ('同行少女', '你看，檐角那只燕子已经飞出去了。说不定山的另一边，早已是晴天。'),
            ('青衫客', '那便记下这场雨吧。许多年后回望，或许最先想起的，就是今日窗前的茶香。'),
            ('客栈掌柜', '慢些走。过桥之后向东，桃花最多的地方，就是你们要找的村子。'),
            ('同行少女', '好，我们天晴就出发。'),
        ]
        return [dict(speaker=speaker, text=text, time=f'20:18:{12 + i * 3:02d}', session='demo', sequence=i + 1)
                for i, (speaker, text) in enumerate(lines)]


def acquire_instance_lock():
    """在同一用户的共享目录加锁，避免多个解压副本重复采集。"""
    directory = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'JinshuDialogue'
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / 'desktop.lock'))
    # 采集可以持续数小时，不能仅因锁文件时间较长而判为失效。
    lock.setStaleLockTime(0)
    if lock.tryLock(0):
        return lock
    if lock.error() == QLockFile.LockFailedError:
        return None
    raise OSError(f'无法创建运行锁，请检查目录写入权限：{directory}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='金书 · 对话录桌面阅读器')
    parser.add_argument('--demo', action='store_true', help='显示原创示例，不连接游戏')
    parser.add_argument('--smoke-test', action='store_true', help='启动后自动关闭，供便携包验收')
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('金书对话录')
    app.setOrganizationName('JinshuDialogue')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    instance_lock = None
    if not args.demo and not args.smoke_test:
        try:
            instance_lock = acquire_instance_lock()
        except OSError as error:
            QMessageBox.critical(None, '无法启动金书对话录', str(error))
            return 1
        if instance_lock is None:
            QMessageBox.information(None, '金书对话录已经在运行',
                                    '金书 · 对话录已经在运行。请切换到已有窗口；如需打开另一个副本，请先关闭原窗口。')
            return 0
    try:
        window = MainWindow(demo=args.demo)
        window.show()
        if args.smoke_test:
            QTimer.singleShot(800, window.close)
        return app.exec()
    finally:
        if instance_lock is not None:
            instance_lock.unlock()


if __name__ == '__main__':
    raise SystemExit(main())
