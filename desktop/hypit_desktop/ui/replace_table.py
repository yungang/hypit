"""One row per clone task: theme (text) plus optional replacement images for role, product and background."""
from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHeaderView, QMenu, QTableWidget,
                               QTableWidgetItem)

TOPIC_COL = 0
IMAGE_COLUMNS = {1: ("role_image", "角色"), 2: ("product_image", "商品"), 3: ("background_image", "背景")}
THUMB = 64
ROW_HEIGHT = THUMB + 12
AUTO_ROLE = Qt.UserRole + 1  # on the theme cell: True while the text is the automatic default
PATH_ROLE = Qt.UserRole      # on image cells: the image path ('' = none)
IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.webp *.bmp)"
EMPTY_HINT = "双击选择图片"


class ReplaceTable(QTableWidget):
    rows_changed = Signal()

    def __init__(self):
        super().__init__(0, 1 + len(IMAGE_COLUMNS))
        self._busy = False  # True while the program (not the user) edits cells
        self.setHorizontalHeaderLabels(["主题"] + [f"{label}(图片,可选)" for _, label in IMAGE_COLUMNS.values()])
        self.setIconSize(QSize(THUMB, THUMB))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        header = self.horizontalHeader()
        header.setSectionResizeMode(TOPIC_COL, QHeaderView.Stretch)
        for col in IMAGE_COLUMNS:
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.itemChanged.connect(self._on_item_changed)
        self.setMinimumHeight(ROW_HEIGHT * 3 + 34)

    # --- rows ------------------------------------------------------------------
    def add_row(self, topic: str = "", role: str = "", product: str = "", background: str = "",
                auto: bool = True) -> int:
        row = self.rowCount()
        self._busy = True
        self.insertRow(row)
        item = QTableWidgetItem(topic)
        item.setData(AUTO_ROLE, auto)
        self.setItem(row, TOPIC_COL, item)
        for col, path in zip(IMAGE_COLUMNS, (role, product, background)):
            cell = QTableWidgetItem()
            cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.setItem(row, col, cell)
            self._show_image(cell, path)
        self._busy = False
        self.rows_changed.emit()
        return row

    def remove_selected_rows(self) -> None:
        for row in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(row)
        self.rows_changed.emit()

    def reset(self, topic: str = "") -> None:
        """Back to one empty row that carries the automatic default theme."""
        self._busy = True
        self.setRowCount(0)
        self._busy = False
        self.add_row(topic)

    def load_rows(self, rows: list[dict]) -> None:
        """Show saved rows (editing a queued task); their themes count as user-written."""
        self._busy = True
        self.setRowCount(0)
        self._busy = False
        for r in rows:
            self.add_row(r.get("topic", ""), r.get("role_image", ""), r.get("product_image", ""),
                         r.get("background_image", ""), auto=False)

    def rows(self) -> list[dict]:
        result = []
        for row in range(self.rowCount()):
            entry = {"topic": self.item(row, TOPIC_COL).text().strip()}
            for col, (key, _) in IMAGE_COLUMNS.items():
                entry[key] = self.item(row, col).data(PATH_ROLE) or ""
            result.append(entry)
        return result

    def set_default_topic(self, text: str) -> None:
        """Update every theme the user has not edited."""
        self._busy = True
        for row in range(self.rowCount()):
            item = self.item(row, TOPIC_COL)
            if item.data(AUTO_ROLE):
                item.setText(text)
        self._busy = False

    # --- images -----------------------------------------------------------------
    def set_image(self, row: int, col: int, path: str) -> None:
        self._busy = True
        self._show_image(self.item(row, col), path)
        self._busy = False
        self.rows_changed.emit()

    def _show_image(self, cell: QTableWidgetItem, path: str) -> None:
        cell.setData(PATH_ROLE, path)
        pixmap = QPixmap(path) if path else QPixmap()
        if path and not pixmap.isNull():
            cell.setIcon(QIcon(pixmap.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            cell.setText(Path(path).name)
            cell.setForeground(QBrush())
            cell.setToolTip(path)
            return
        cell.setIcon(QIcon())
        cell.setText(f"无法读取:{Path(path).name}" if path else EMPTY_HINT)
        cell.setForeground(QBrush(QColor("#aaa" if not path else "#c33")))
        cell.setToolTip(path)

    def _choose(self, row: int, col: int, *_) -> None:
        start = self.item(row, col).data(PATH_ROLE) or ""
        path, _ = QFileDialog.getOpenFileName(self, f"选择{IMAGE_COLUMNS[col][1]}图片", start, IMAGE_FILTER)
        if path:
            self.set_image(row, col, path)

    def _clear(self, row: int, col: int, *_) -> None:
        self.set_image(row, col, "")

    # --- events -------------------------------------------------------------------
    def _on_double_click(self, item: QTableWidgetItem) -> None:
        if item.column() in IMAGE_COLUMNS:
            self._choose(item.row(), item.column())

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._busy or item.column() != TOPIC_COL:
            return
        self._busy = True
        item.setData(AUTO_ROLE, False)  # the user wrote this theme; stop auto-updating it
        self._busy = False
        self.rows_changed.emit()

    def _menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid() or index.column() not in IMAGE_COLUMNS:
            return
        row, col = index.row(), index.column()
        menu = QMenu(self)
        menu.addAction("选择图片…", partial(self._choose, row, col))
        has_image = bool(self.item(row, col).data(PATH_ROLE))
        menu.addAction("清除", partial(self._clear, row, col)).setEnabled(has_image)
        menu.exec(self.viewport().mapToGlobal(pos))
