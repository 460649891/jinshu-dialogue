"""Bounded, widget-free dialogue list and its reader delegate."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

RecordRole = int(Qt.UserRole) + 1


def format_records(records, include_speaker=True):
    """保持记录顺序，生成适合复制和导出的纯文本。"""
    return '\n\n'.join(
        f"{record['speaker']}：{record['text']}" if include_speaker else record['text']
        for record in records
    )


class DialogueListModel(QAbstractListModel):
    def __init__(self, parent=None, max_records=2000):
        super().__init__(parent)
        self.records = []
        self._search_texts = []
        self.max_records = max(1, max_records)
        self.total_received = 0

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.records):
            return None
        record = self.records[index.row()]
        if role == RecordRole:
            return record
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            return f"{record['speaker']}：{record['text']}"
        if role == Qt.ToolTipRole:
            return record['text']
        return None

    def append_records(self, records):
        clean = []
        for record in records:
            text = str(record.get('text') or '')
            if not text.strip():
                continue
            clean.append({**record, 'text': text,
                          'speaker': str(record.get('speaker') or '').strip() or '未知人物',
                          'time': str(record.get('time') or '')})
        if not clean:
            return 0
        self.total_received += len(clean)
        overflow = max(0, len(self.records) + len(clean) - self.max_records)
        remove = min(overflow, len(self.records))
        if remove:
            self.beginRemoveRows(QModelIndex(), 0, remove - 1)
            del self.records[:remove]
            del self._search_texts[:remove]
            self.endRemoveRows()
        clean = clean[max(0, overflow - remove):]
        first = len(self.records)
        self.beginInsertRows(QModelIndex(), first, first + len(clean) - 1)
        self.records.extend(clean)
        self._search_texts.extend(f"{record['speaker']}\n{record['text']}".casefold() for record in clean)
        self.endInsertRows()
        return len(clean)

    def search_rows(self, query, start=0):
        """只搜索保留的原始记录，可从新增区间继续查找。"""
        query = query.casefold()
        return [row for row in range(max(0, start), len(self.records))
                if query and query in self._search_texts[row]]


class DialogueDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(240, 110)

    def paint(self, painter, option, index):
        record = index.data(RecordRole)
        if not record:
            return
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        rect = option.rect
        painter.fillRect(rect, QColor('#18332f' if selected else '#141f2b' if hovered else '#101923'))
        if selected:
            painter.fillRect(QRect(rect.left(), rect.top() + 12, 3, rect.height() - 24), QColor('#68d5bd'))
        painter.setPen(QColor('#263340'))
        painter.drawLine(rect.left() + 18, rect.bottom(), rect.right() - 18, rect.bottom())
        font = QFont(option.font)
        font.setPointSizeF(10.5)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor('#8ae1cc' if selected else '#d7e7ed'))
        name_rect = QRect(rect.left() + 20, rect.top() + 15, max(20, rect.width() - 130), 24)
        painter.drawText(name_rect, Qt.AlignVCenter, QFontMetrics(font).elidedText(record['speaker'], Qt.ElideRight, name_rect.width()))
        font.setPointSizeF(8.5)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor('#9baebc'))
        time_text = record['time'].split('T')[-1].split(' ')[-1][:8]
        painter.drawText(QRect(rect.right() - 100, rect.top() + 15, 80, 24), Qt.AlignRight | Qt.AlignVCenter, time_text)
        font.setPointSizeF(10.5)
        painter.setFont(font)
        painter.setPen(QColor('#bdcbd6'))
        summary = ' '.join(record['text'].split())
        metrics = QFontMetrics(font)
        width = max(20, rect.width() - 40)
        first_line = ''
        split_at = 0
        # Two bounded preview lines; full text lives in the selectable detail pane.
        for pos, character in enumerate(summary[:180]):
            if metrics.horizontalAdvance(first_line + character) > width:
                split_at = pos
                break
            first_line += character
        else:
            split_at = len(first_line)
        painter.drawText(QRect(rect.left() + 20, rect.top() + 46, width, 24), Qt.AlignVCenter, first_line)
        rest = summary[split_at:]
        painter.drawText(QRect(rect.left() + 20, rect.top() + 72, width, 22), Qt.AlignVCenter,
                         metrics.elidedText(rest, Qt.ElideRight, width))
        if option.state & QStyle.State_HasFocus:
            painter.setPen(QPen(QColor('#68d5bd'), 1))
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
        painter.restore()
