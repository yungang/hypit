"""Cost statistics: totals, a daily chart, and breakdowns by task and by model."""
from __future__ import annotations

import time
from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..db import TaskStore

RANGES = [("今天", 1), ("近 7 天", 7), ("近 30 天", 30), ("全部", 0)]
CHART_DAYS = 14


def day_start(days_back: int) -> float:
    """Local midnight `days_back` days ago (0 = today)."""
    d = date.today() - timedelta(days=days_back)
    return time.mktime(d.timetuple())


class CostChart(QWidget):
    """Plain bar chart of per-day cost."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(170)
        self._data: list[tuple[str, float]] = []

    def set_data(self, data: list[tuple[str, float]]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._data:
            return
        w, h = self.width(), self.height()
        top, bottom = 18, 22
        peak = max((v for _, v in self._data), default=0) or 1.0
        slot = w / len(self._data)
        bar_w = slot * 0.6
        for i, (label, value) in enumerate(self._data):
            bar_h = (h - top - bottom) * value / peak
            x = i * slot + (slot - bar_w) / 2
            y = h - bottom - bar_h
            p.fillRect(QRectF(x, y, bar_w, max(bar_h, 1)), QColor("#5b8def" if value else "#d8d8d8"))
            p.setPen(QColor("#555"))
            p.drawText(QRectF(i * slot, h - bottom + 2, slot, bottom - 2), Qt.AlignHCenter | Qt.AlignTop, label)
            if value:
                p.drawText(QRectF(i * slot, y - 16, slot, 14), Qt.AlignHCenter | Qt.AlignBottom, f"${value:.2f}")


def stat_card(title: str) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setStyleSheet("QFrame { border: 1px solid #d0d0d0; border-radius: 8px; background: white; }")
    caption = QLabel(title)
    caption.setStyleSheet("color: #777; border: none;")
    value = QLabel("-")
    value.setStyleSheet("font-size: 20px; font-weight: 600; border: none;")
    layout = QVBoxLayout(frame)
    layout.addWidget(caption)
    layout.addWidget(value)
    return frame, value


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().hide()
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(160)
    return table


def fill(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, text in enumerate(row):
            item = QTableWidgetItem(text)
            if j > 0:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(i, j, item)


class StatsPage(QWidget):
    def __init__(self, store: TaskStore):
        super().__init__()
        self._store = store

        title = QLabel("花费统计")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        note = QLabel("按每次运行的花费汇总,删除任务后记录仍保留。")
        note.setStyleSheet("color: #777;")

        cards = QHBoxLayout()
        self._cards: dict[str, QLabel] = {}
        for key, caption in (("today", "今天"), ("week", "近 7 天"), ("month", "近 30 天"),
                             ("all", "累计"), ("runs", "运行次数(累计)")):
            frame, value = stat_card(caption)
            self._cards[key] = value
            cards.addWidget(frame)

        self.range_combo = QComboBox()
        for label, days in RANGES:
            self.range_combo.addItem(label, days)
        self.range_combo.setCurrentIndex(2)
        self.range_combo.currentIndexChanged.connect(self._on_range)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("下方明细的时间范围:"))
        range_row.addWidget(self.range_combo)
        range_row.addStretch()

        self.chart = CostChart()
        self.by_task = make_table(["任务", "运行次数", "花费"])
        self.by_model = make_table(["模型", "运行次数", "花费"])
        self.by_day = make_table(["日期", "运行次数", "花费"])

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addWidget(title)
        layout.addWidget(note)
        layout.addLayout(cards)
        layout.addWidget(QLabel(f"最近 {CHART_DAYS} 天每日花费"))
        layout.addWidget(self.chart)
        layout.addLayout(range_row)
        layout.addWidget(QLabel("按任务"))
        layout.addWidget(self.by_task)
        layout.addWidget(QLabel("按模型"))
        layout.addWidget(self.by_model)
        layout.addWidget(QLabel("按天"))
        layout.addWidget(self.by_day)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.refresh()

    def _on_range(self, *_) -> None:
        self.refresh()

    def refresh(self) -> None:
        s = self._store
        self._cards["today"].setText(f"${s.cost_total(day_start(0))[1]:.2f}")
        self._cards["week"].setText(f"${s.cost_total(day_start(6))[1]:.2f}")
        self._cards["month"].setText(f"${s.cost_total(day_start(29))[1]:.2f}")
        runs, total = s.cost_total(0)
        self._cards["all"].setText(f"${total:.2f}")
        self._cards["runs"].setText(str(runs))

        per_day = {day: cost for day, _, cost in s.cost_by_day(day_start(CHART_DAYS - 1))}
        days = [date.today() - timedelta(days=n) for n in range(CHART_DAYS - 1, -1, -1)]
        self.chart.set_data([(d.strftime("%m-%d"), per_day.get(d.isoformat(), 0.0)) for d in days])

        span = self.range_combo.currentData()
        since = day_start(span - 1) if span else 0
        fill(self.by_task, [[title or f"任务 {tid}", str(n), f"${c:.2f}"]
                            for tid, title, n, c in s.cost_by_task(since)])
        fill(self.by_model, [[model or "(未记录)", str(n), f"${c:.2f}"] for model, n, c in s.cost_by_model(since)])
        fill(self.by_day, [[day, str(n), f"${c:.2f}"] for day, n, c in reversed(s.cost_by_day(since))])
