"""Collect the user's feedback on a finished video (what to change, optionally where)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout)


class FeedbackDialog(QDialog):
    def __init__(self, title: str, duration_hint: float = 0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("不满意,重做")
        self.resize(520, 340)
        intro = QLabel(f"「{title}」哪里不满意?说清楚想改什么,AI 导演会只改这部分,其余沿用(省钱)。")
        intro.setWordWrap(True)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("例如:结尾太平淡,想换成更夸张的反转;女主的造型太严肃,要更活泼……")
        self.at_check = QCheckBox("针对视频中的某个时间点")
        self.at_seconds = QDoubleSpinBox()
        self.at_seconds.setRange(0, max(duration_hint, 600))
        self.at_seconds.setDecimals(1)
        self.at_seconds.setSuffix(" 秒")
        self.at_seconds.setEnabled(False)
        self.at_check.toggled.connect(self.at_seconds.setEnabled)
        at_row = QHBoxLayout()
        at_row.addWidget(self.at_check)
        at_row.addWidget(self.at_seconds)
        at_row.addStretch()
        note = QLabel("重做会作为新任务加入执行队列,开始前仍会让你确认预估费用。")
        note.setStyleSheet("color: #666;")
        ok = QPushButton("提交重做")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.text, 1)
        layout.addLayout(at_row)
        layout.addWidget(note)
        layout.addLayout(buttons)

    def _accept(self, *_) -> None:
        if not self.text.toPlainText().strip():
            QMessageBox.warning(self, "提示", "请先写一下哪里不满意。")
            return
        self.accept()

    def result_value(self) -> tuple[str, Optional[float]]:
        return (self.text.toPlainText().strip(),
                self.at_seconds.value() if self.at_check.isChecked() else None)
