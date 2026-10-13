"""Per-run history of one task: result, cost and times."""
from __future__ import annotations

import time

from PySide6.QtWidgets import (QAbstractItemView, QDialog, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..db import TaskStore
from .task_lists import STATUS_LABELS


def fmt_time(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "-"


class RunsDialog(QDialog):
    def __init__(self, store: TaskStore, task_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行记录")
        self.resize(640, 320)
        runs = store.runs(task_id)
        table = QTableWidget(len(runs), 5)
        table.setHorizontalHeaderLabels(["第几次", "结果", "花费", "开始", "结束"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        for i, run in enumerate(runs):
            cells = [str(run["run_no"]), STATUS_LABELS.get(run["status"], run["status"]),
                     f"${run['cost']:.2f}", fmt_time(run["started"]), fmt_time(run["finished"])]
            for j, text in enumerate(cells):
                table.setItem(i, j, QTableWidgetItem(text))
        total = QLabel(f"累计 ${sum(r['cost'] for r in runs):.2f},共 {len(runs)} 次运行")
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(table)
        layout.addWidget(total)
        layout.addWidget(close)
