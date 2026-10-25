from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QVBoxLayout)

from ..agent.replay import SCENARIOS
from ..settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(680, 520)
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

        self.backend = QComboBox()
        self.backend.addItem("演示回放(不联网,不花钱)", "replay")
        self.backend.addItem("AI 导演 + Hypit 真实生成(会扣 HypiHub 积分和 AI 费用)", "agent")
        self.backend.addItem("Hypit 固定示例(开发用,会扣 HypiHub 积分)", "hypit")
        self.backend.setCurrentIndex(max(0, self.backend.findData(settings.get("backend"))))
        self.llm_model = QLineEdit(settings.get("llm_model"))
        self.llm_model.setPlaceholderText("AI 导演使用的模型,默认 deepseek-flash")
        self.llm_key_env = QLineEdit(settings.get("llm_key_env"))
        self.llm_key_env.setPlaceholderText("保存 AI 密钥的环境变量名,默认 DEEPSEEK_API_KEY")
        self.launcher = QLineEdit(settings.get("hypit_launcher"))
        self.launcher.setPlaceholderText("Hypit 启动文件 hypit.mjs(留空用默认位置)")
        self.use_proxy = QCheckBox("Hypit 联网时使用系统代理环境变量(HTTPS_PROXY 等)")
        self.use_proxy.setChecked(bool(settings.get("use_env_proxy")))
        self.project_dir = QLineEdit(settings.get("hypit_project_dir"))
        self.project_dir.setPlaceholderText("开发用:直接使用已有的 Hypit 项目目录(留空则按模板新建)")
        self.run_source = QLineEdit(settings.get("hypit_run_source"))
        self.run_source.setPlaceholderText("开发用:运行文件,默认 reference.svrun")

        form = QFormLayout()
        form.addRow("生成后端", self.backend)
        form.addRow("AI 导演模型", self.llm_model)
        form.addRow("AI 密钥环境变量", self.llm_key_env)
        form.addRow("Hypit 启动文件", self.launcher)
        form.addRow("", self.use_proxy)
        form.addRow("项目目录(开发)", self.project_dir)
        form.addRow("运行文件(开发)", self.run_source)
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
        self._settings.set("backend", self.backend.currentData())
        self._settings.set("llm_model", self.llm_model.text().strip() or "deepseek-flash")
        self._settings.set("llm_key_env", self.llm_key_env.text().strip() or "DEEPSEEK_API_KEY")
        self._settings.set("hypit_launcher", self.launcher.text().strip())
        self._settings.set("use_env_proxy", self.use_proxy.isChecked())
        self._settings.set("hypit_project_dir", self.project_dir.text().strip())
        self._settings.set("hypit_run_source", self.run_source.text().strip())
        self._settings.set("max_concurrent", self.concurrent.value())
        self._settings.set("export_dir", self.export_dir.text().strip())
        self._settings.set("scenario", self.scenario.currentData())
        self._settings.set("replay_speed", self.speed.value())
        self.accept()
