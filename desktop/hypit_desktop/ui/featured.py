"""Card strip of the internal featured library, filtered by platform."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QTabBar, QVBoxLayout, QWidget)

from ..db import TaskStore
from ..featured_seed import FEATURED_PLATFORMS, PLATFORM_NAMES
from .common import cover_pixmap

CARD_W, COVER_H = 210, 118


class FeaturedCard(QFrame):
    clicked = Signal(object)  # entry dict

    def __init__(self, entry: dict):
        super().__init__()
        self._entry = entry
        self.setFixedWidth(CARD_W)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("FeaturedCard { border: 1px solid #d0d0d0; border-radius: 8px; background: white; }"
                           "FeaturedCard:hover { border-color: #5b8def; }")
        cover = QLabel()
        cover.setPixmap(cover_pixmap(entry["cover"], CARD_W - 12, COVER_H,
                                     PLATFORM_NAMES.get(entry["platform"], ""), entry["id"]))
        title = QLabel(entry["title"])
        title.setStyleSheet("font-weight: 600;")
        desc = QLabel(entry["description"])
        desc.setStyleSheet("color: #777;")
        desc.setWordWrap(True)
        desc.setMaximumHeight(36)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(cover)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._entry)


class FeaturedStrip(QWidget):
    picked = Signal(object)   # entry dict: url + params to fill the form with
    manage_requested = Signal()

    def __init__(self, store: TaskStore):
        super().__init__()
        self._store = store
        self._platform = ""  # "" = all

        header = QLabel("热门参考(点击卡片自动填入参数)")
        header.setStyleSheet("font-weight: 600;")
        manage = QPushButton("管理精选库…")
        manage.clicked.connect(self.manage_requested)
        self._tabs = QTabBar()
        self._tabs.setExpanding(False)
        self._tabs.addTab("全部")
        for _, name in FEATURED_PLATFORMS:
            self._tabs.addTab(name)
        self._tabs.currentChanged.connect(self._on_tab)

        top = QHBoxLayout()
        top.addWidget(header)
        top.addStretch()
        top.addWidget(manage)

        self._cards = QHBoxLayout()
        self._cards.setAlignment(Qt.AlignLeft)
        holder = QWidget()
        holder.setLayout(self._cards)
        self._scroll = QScrollArea()
        self._scroll.setWidget(holder)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(COVER_H + 120)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self._tabs)
        layout.addWidget(self._scroll)
        self.refresh()

    def _on_tab(self, index: int) -> None:
        self._platform = "" if index == 0 else FEATURED_PLATFORMS[index - 1][0]
        self.refresh()

    def refresh(self) -> None:
        while self._cards.count():
            item = self._cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = [e for e in self._store.featured() if not self._platform or e["platform"] == self._platform]
        if not entries:
            hint = QLabel("这个平台还没有精选,点右上角「管理精选库」添加。")
            hint.setStyleSheet("color: #888;")
            self._cards.addWidget(hint)
        for entry in entries:
            card = FeaturedCard(entry)
            card.clicked.connect(self.picked)
            self._cards.addWidget(card)
