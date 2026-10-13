from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QVBoxLayout)

from ..agent.replay import SCENARIOS
from ..settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(480, 260)
        self._settings = settings

        self.export_dir = QLineEdit(settings.get("export_dir"))
        self.export_dir.setPlaceholderText("每次导出时询问")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.export_dir, 1)
        dir_row.addWidget(browse)

        self.scenario = QComboBox()
        for sid, (label, _) in SCENARIOS.items():
            self.scenario.addItem(label, sid)
        self.scenario.setCurrentIndex(max(0, self.scenario.findData(settings.get("scenario"))))
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 20)
        self.speed.setSingleStep(0.5)
        self.speed.setValue(float(settings.get("replay_speed")))

        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 8)
        self.concurrent.setValue(int(settings.get("max_concurrent")))
        self.concurrent.setToolTip("同时执行的任务数;超出的在执行队列里排队")

        form = QFormLayout()
        form.addRow("同时执行任务数", self.concurrent)
        form.addRow("发布包默认导出位置", dir_row)
        form.addRow("演示场景(开发用)", self.scenario)
        form.addRow("演示播放速度(开发用)", self.speed)

        ok = QPushButton("保存")
        ok.clicked.connect(self._save)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("演示选项在接入真实 agent 后会移除。"))
        layout.addStretch()
        layout.addLayout(buttons)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择默认导出位置", self.export_dir.text())
        if chosen:
            self.export_dir.setText(chosen)

    def _save(self) -> None:
        self._settings.set("max_concurrent", self.concurrent.value())
        self._settings.set("export_dir", self.export_dir.text().strip())
        self._settings.set("scenario", self.scenario.currentData())
        self._settings.set("replay_speed", self.speed.value())
        self.accept()
