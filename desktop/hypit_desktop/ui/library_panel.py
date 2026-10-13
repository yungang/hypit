"""Works library: browse finished videos, rate, tag, filter, keep or reject."""
from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

from .. import media_info
from ..db import TaskStore
from .common import placeholder_pixmap

STATUSES = [("undecided", "待定"), ("kept", "保留"), ("rejected", "淘汰")]
THUMB_W, THUMB_H = 128, 76


def stars(rating: int) -> str:
    return "★" * rating + "☆" * (5 - rating)


class LibraryPanel(QWidget):
    publish_requested = Signal(int)    # artifact id
    open_task_requested = Signal(int)  # task id

    def __init__(self, store: TaskStore, thumbs_dir: Path):
        super().__init__()
        self._store = store
        self._thumbs_dir = thumbs_dir
        self._current: int | None = None

        title = QLabel("作品库")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.min_rating = QComboBox()
        self.min_rating.addItem("评分不限", 0)
        for n in range(1, 6):
            self.min_rating.addItem(f"≥ {n} 星", n)
        self.status_filter = QComboBox()
        self.status_filter.addItem("全部状态", "")
        for key, label in STATUSES:
            self.status_filter.addItem(label, key)
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("按标题或标签关键词过滤")
        self.keyword.setClearButtonEnabled(True)
        self._count = QLabel("")
        self._count.setStyleSheet("color: #666;")
        cleanup = QPushButton("清理已淘汰…")
        cleanup.clicked.connect(self._cleanup_rejected)
        bar = QHBoxLayout()
        for w in (title, self.min_rating, self.status_filter):
            bar.addWidget(w)
        bar.addWidget(self.keyword, 1)
        bar.addWidget(self._count)
        bar.addWidget(cleanup)
        for w in (self.min_rating, self.status_filter):
            w.currentIndexChanged.connect(self._on_filter_changed)
        self.keyword.textChanged.connect(self._on_filter_changed)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setIconSize(QSize(THUMB_W, THUMB_H))
        self._list.setGridSize(QSize(THUMB_W + 24, THUMB_H + 54))
        self._list.setWordWrap(True)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.currentItemChanged.connect(self._on_select)

        # --- detail ---
        self._name = QLabel("选择一个作品")
        self._name.setWordWrap(True)
        self._name.setStyleSheet("font-weight: 600;")
        self._star_buttons: list[QPushButton] = []
        stars_row = QHBoxLayout()
        for n in range(1, 6):
            btn = QPushButton("☆")
            btn.setFixedWidth(34)
            btn.clicked.connect(partial(self._set_rating, n))
            self._star_buttons.append(btn)
            stars_row.addWidget(btn)
        stars_row.addStretch()
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("标签,用逗号分隔")
        self.tags.editingFinished.connect(self._save_tags)
        self._status_buttons: dict[str, QPushButton] = {}
        status_group = QButtonGroup(self)
        status_group.setExclusive(True)
        status_row = QHBoxLayout()
        for key, label in STATUSES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(partial(self._set_status, key))
            status_group.addButton(btn)
            self._status_buttons[key] = btn
            status_row.addWidget(btn)
        play = QPushButton("播放")
        play.clicked.connect(self._play)
        folder = QPushButton("所在文件夹")
        folder.clicked.connect(self._open_folder)
        publish = QPushButton("发布…")
        publish.clicked.connect(self._emit_publish)
        task_btn = QPushButton("查看任务")
        task_btn.clicked.connect(self._open_task)
        actions = QHBoxLayout()
        for w in (play, folder, publish, task_btn):
            actions.addWidget(w)
        self._detail = QWidget()
        detail = QVBoxLayout(self._detail)
        detail.addWidget(self._name)
        detail.addLayout(stars_row)
        detail.addWidget(self.tags)
        detail.addLayout(status_row)
        detail.addLayout(actions)
        detail.addStretch()
        self._detail.setEnabled(False)
        self._detail.setMinimumWidth(300)

        split = QSplitter()
        split.addWidget(self._list)
        split.addWidget(self._detail)
        split.setStretchFactor(0, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addLayout(bar)
        layout.addWidget(split, 1)
        self.refresh()

    def _on_filter_changed(self, *_) -> None:
        self.refresh()

    def _emit_publish(self, *_) -> None:
        if self._current:
            self.publish_requested.emit(self._current)

    # --- list --------------------------------------------------------------------
    def _matches(self, row) -> bool:
        if row["rating"] < self.min_rating.currentData():
            return False
        status = self.status_filter.currentData()
        if status and row["status"] != status:
            return False
        key = self.keyword.text().strip().lower()
        return not key or key in row["title"].lower() or key in row["tags"].lower()

    def _icon(self, row) -> QIcon:
        thumb = self._thumbs_dir / f"{row['id']}.png"
        if not thumb.is_file():
            media_info.make_thumbnail(row["path"], thumb)
        if thumb.is_file():
            return QIcon(str(thumb))
        return QIcon(placeholder_pixmap(THUMB_W, THUMB_H, "▶", row["id"]))

    def refresh(self, select_id: int | None = None) -> None:
        keep = select_id if select_id is not None else self._current
        rows = self._store.artifacts()
        shown = [r for r in rows if self._matches(r)]
        self._list.blockSignals(True)
        self._list.clear()
        for row in shown:
            label = {"rejected": "（淘汰）", "kept": "（保留）"}.get(row["status"], "")
            item = QListWidgetItem(self._icon(row), f"{stars(row['rating'])}\n{row['title']}{label}")
            item.setData(Qt.UserRole, row["id"])
            if row["status"] == "rejected":
                item.setForeground(QBrush(QColor("#aaa")))
            self._list.addItem(item)
            if row["id"] == keep:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)
        self._count.setText(f"{len(shown)} / {len(rows)}")
        item = self._list.currentItem()
        self._current = item.data(Qt.UserRole) if item else None
        self._show_detail(self._store.artifact(self._current) if self._current else None)

    def _on_select(self, item: QListWidgetItem | None) -> None:
        self._current = item.data(Qt.UserRole) if item else None
        self._show_detail(self._store.artifact(self._current) if self._current else None)

    def _show_detail(self, row) -> None:
        self._detail.setEnabled(row is not None)
        if row is None:
            self._name.setText("选择一个作品")
            self.tags.clear()
            for btn in self._star_buttons:
                btn.setText("☆")
            group = self._status_buttons["undecided"].group()
            group.setExclusive(False)
            for btn in self._status_buttons.values():
                btn.setChecked(False)
            group.setExclusive(True)
            return
        self._current = row["id"]
        self._name.setText(row["title"])
        for n, btn in enumerate(self._star_buttons, 1):
            btn.setText("★" if n <= row["rating"] else "☆")
        self.tags.setText(row["tags"])
        self._status_buttons[row["status"]].setChecked(True)

    # --- edits -----------------------------------------------------------------------
    def _set_rating(self, value: int, *_) -> None:
        if self._current is None:
            return
        row = self._store.artifact(self._current)
        self._store.update_artifact(self._current, rating=0 if row["rating"] == value else value)
        self.refresh()

    def _save_tags(self) -> None:
        if self._current is None:
            return
        tags = ",".join(t.strip() for t in self.tags.text().replace("，", ",").split(",") if t.strip())
        self._store.update_artifact(self._current, tags=tags)
        self.refresh()

    def _set_status(self, status: str, *_) -> None:
        if self._current is not None:
            self._store.update_artifact(self._current, status=status)
            self.refresh()

    def _cleanup_rejected(self) -> None:
        rejected = [r for r in self._store.artifacts() if r["status"] == "rejected"]
        if not rejected:
            QMessageBox.information(self, "清理", "没有标记为淘汰的作品。")
            return
        if QMessageBox.question(
                self, "清理已淘汰作品",
                f"将永久删除 {len(rejected)} 个已淘汰作品及其视频文件,无法恢复。确定吗?") != QMessageBox.Yes:
            return
        for row in rejected:
            try:
                if Path(row["path"]).is_file():
                    os.remove(row["path"])
            except OSError:
                pass
            self._store.delete_artifact(row["id"])
        self._current = None
        self.refresh()

    # --- actions ---------------------------------------------------------------------
    def _play(self) -> None:
        row = self._store.artifact(self._current) if self._current else None
        if row is None:
            return
        if Path(row["path"]).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(row["path"]).resolve())))
        else:
            QMessageBox.information(self, "播放", f"视频文件不存在:{row['path']}\n(演示数据没有真实文件)")

    def _open_folder(self) -> None:
        row = self._store.artifact(self._current) if self._current else None
        if row is not None and Path(row["path"]).parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(row["path"]).parent.resolve())))

    def _open_task(self) -> None:
        row = self._store.artifact(self._current) if self._current else None
        if row is not None and row["task_id"] and self._store.task(row["task_id"]) is not None:
            self.open_task_requested.emit(row["task_id"])
