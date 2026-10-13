"""The two queue lists. Dragging only reports what was dropped where; the window
decides what that means for the queues and rebuilds the lists."""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

STATUS_LABELS = {"pending": "待执行", "waiting": "排队中", "running": "执行中", "success": "已完成",
                 "cancelled": "已取消", "failed": "失败", "interrupted": "已中断"}
STATUS_ICONS = {"pending": "⏸", "waiting": "⏳", "running": "▶", "success": "✅",
                "cancelled": "⏹", "failed": "❌", "interrupted": "⚠"}
DRAGGABLE = ("pending", "waiting")  # can be reordered / moved between the queues
RESETTABLE = ("cancelled", "interrupted", "failed")  # can be dragged back to the to-do queue


class TaskListWidget(QListWidget):
    dropped = Signal(list, int)  # dragged task ids, row to insert at (in this list's display order)

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)

    def set_tasks(self, rows, selected_id: int | None = None) -> None:
        """Rebuild the list from task rows (already in display order)."""
        self.blockSignals(True)
        self.clear()
        for position, row in enumerate(rows):
            status = row["status"]
            extra = f" · 第 {self._waiting_rank(rows, position)} 位" if status == "waiting" else ""
            item = QListWidgetItem(f"{STATUS_ICONS.get(status, '')} {row['title']}\n"
                                   f"{STATUS_LABELS.get(status, status)}{extra} · 累计 ${row['total_cost']:.2f}")
            item.setSizeHint(QSize(100, 46))
            item.setData(Qt.UserRole, row["id"])
            item.setData(Qt.UserRole + 1, status)
            if status not in DRAGGABLE + RESETTABLE:
                item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
            if status == "running":
                item.setBackground(QBrush(QColor("#e8f1ff")))
                item.setToolTip("执行中:可以停止,不能编辑或拖动")
            elif status not in DRAGGABLE:
                item.setForeground(QBrush(QColor("#888")))
            self.addItem(item)
            if row["id"] == selected_id:
                self.setCurrentItem(item)
        self.blockSignals(False)

    @staticmethod
    def _waiting_rank(rows, position: int) -> int:
        return sum(1 for r in rows[:position + 1] if r["status"] == "waiting")

    def task_ids(self) -> list[tuple[int, str]]:
        return [(self.item(i).data(Qt.UserRole), self.item(i).data(Qt.UserRole + 1)) for i in range(self.count())]

    def _drop_row(self, pos) -> int:
        index = self.indexAt(pos)
        if not index.isValid():
            return self.count()
        below = pos.y() > self.visualRect(index).center().y()
        return index.row() + (1 if below else 0)

    def _emit_dropped(self, ids: list, row: int) -> None:
        self.dropped.emit(ids, row)

    def dropEvent(self, event) -> None:
        source = event.source()
        if not isinstance(source, TaskListWidget):
            event.ignore()
            return
        ids = [it.data(Qt.UserRole) for it in source.selectedItems()]
        row = self._drop_row(event.position().toPoint())
        # Do not let Qt move the item itself (and do not let the source remove it).
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
        if ids:
            QTimer.singleShot(0, partial(self._emit_dropped, ids, row))
