"""Add, edit and remove entries of the internal featured library."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout)

from ..briefs import ASPECTS, LANGUAGES, MARKETS
from ..db import TaskStore
from ..featured_seed import FEATURED_PLATFORMS, PLATFORM_NAMES


class FeaturedDialog(QDialog):
    def __init__(self, store: TaskStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理精选库")
        self.resize(760, 520)
        self._store = store
        self._current: int | None = None

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)

        self.platform = QComboBox()
        for pid, name in FEATURED_PLATFORMS:
            self.platform.addItem(name, pid)
        self.title = QLineEdit()
        self.description = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("视频链接")
        self.cover = QLineEdit()
        self.cover.setPlaceholderText("封面图片(可选,留空用默认色块)")
        browse = QPushButton("选择…")
        browse.clicked.connect(self._browse_cover)
        cover_row = QHBoxLayout()
        cover_row.addWidget(self.cover, 1)
        cover_row.addWidget(browse)
        self.scene = QLineEdit()
        self.market = QComboBox()
        self.market.addItems(MARKETS)
        self.language = QComboBox()
        self.language.addItems(LANGUAGES)
        self.duration = QLineEdit()
        self.duration.setPlaceholderText("例如:15 秒")
        self.aspect = QComboBox()
        self.aspect.addItems(ASPECTS)

        form = QFormLayout()
        form.addRow("平台", self.platform)
        form.addRow("标题", self.title)
        form.addRow("说明", self.description)
        form.addRow("视频链接", self.url)
        form.addRow("封面", cover_row)
        form.addRow("预填:场景", self.scene)
        form.addRow("预填:目标市场", self.market)
        form.addRow("预填:目标语言", self.language)
        form.addRow("预填:时长", self.duration)
        form.addRow("预填:画面比例", self.aspect)

        new_btn = QPushButton("新增")
        new_btn.clicked.connect(self._new)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._delete)
        buttons = QHBoxLayout()
        buttons.addWidget(new_btn)
        buttons.addStretch()
        buttons.addWidget(delete_btn)
        buttons.addWidget(save_btn)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(buttons)
        layout = QHBoxLayout(self)
        layout.addWidget(self._list, 1)
        layout.addLayout(right, 2)

        self._reload()

    def _reload(self, select: int | None = None) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for entry in self._store.featured():
            item = QListWidgetItem(f"[{PLATFORM_NAMES.get(entry['platform'], '')}] {entry['title']}")
            item.setData(Qt.UserRole, entry)
            self._list.addItem(item)
            if entry["id"] == select:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)

    def _on_select(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        entry = item.data(Qt.UserRole)
        self._current = entry["id"]
        p = entry["params"]
        self.platform.setCurrentIndex(max(0, self.platform.findData(entry["platform"])))
        self.title.setText(entry["title"])
        self.description.setText(entry["description"])
        self.url.setText(entry["url"])
        self.cover.setText(entry["cover"])
        self.scene.setText(p.get("scene", ""))
        self.market.setCurrentText(p.get("market", MARKETS[0]))
        self.language.setCurrentText(p.get("language", LANGUAGES[0]))
        self.duration.setText(p.get("duration", ""))
        self.aspect.setCurrentText(p.get("aspect", ASPECTS[0]))

    def _new(self) -> None:
        self._list.clearSelection()
        self._list.setCurrentItem(None)
        self._current = None
        for edit in (self.title, self.description, self.url, self.cover, self.scene, self.duration):
            edit.clear()

    def _browse_cover(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择封面", "", "图片 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.cover.setText(path)

    def params(self) -> dict:
        params = {"market": self.market.currentText(), "language": self.language.currentText(),
                  "aspect": self.aspect.currentText()}
        if self.scene.text().strip():
            params["scene"] = self.scene.text().strip()
        if self.duration.text().strip():
            params["duration"] = self.duration.text().strip()
        return params

    def _save(self) -> None:
        if not self.title.text().strip() or not self.url.text().strip():
            QMessageBox.warning(self, "提示", "标题和视频链接不能为空。")
            return
        args = (self.platform.currentData(), self.title.text().strip(), self.description.text().strip(),
                self.url.text().strip(), self.cover.text().strip(), self.params())
        if self._current is None:
            self._current = self._store.add_featured(*args)
        else:
            self._store.update_featured(self._current, *args)
        self._reload(select=self._current)

    def _delete(self) -> None:
        if self._current is None:
            return
        if QMessageBox.question(self, "删除", "确定从精选库删除这一条吗?") != QMessageBox.Yes:
            return
        self._store.delete_featured(self._current)
        self._current = None
        self._reload()
        self._new()
