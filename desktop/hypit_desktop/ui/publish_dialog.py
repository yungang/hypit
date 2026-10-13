from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from ..db import TaskStore
from ..publish.base import PublishMeta, Publisher
from ..publish.export import export_package
from ..publish.platforms import BY_ID, PLATFORMS
from ..publish.worker import PublishWorker

REGIONS = [("domestic", "国内平台"), ("overseas", "海外平台")]


class PublishDialog(QDialog):
    def __init__(self, store: TaskStore, publisher: Publisher, task_id: int,
                 video_path: str, default_title: str, parent=None, settings=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("一键发布")
        self.resize(560, 640)
        self._store = store
        self._publisher = publisher
        self._task_id = task_id
        self._video_path = video_path
        self._worker: PublishWorker | None = None

        self.title = QLineEdit(default_title)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("视频描述(可选)")
        self.description.setMaximumHeight(80)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("话题标签,用空格分隔(可选)")

        self._checks: dict[str, QCheckBox] = {}
        self._auth_labels: dict[str, QLabel] = {}
        self._auth_buttons: dict[str, QPushButton] = {}
        self._result_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("标题"))
        layout.addWidget(self.title)
        layout.addWidget(QLabel("描述"))
        layout.addWidget(self.description)
        layout.addWidget(self.tags)
        for region, caption in REGIONS:
            layout.addWidget(self._region_box(region, caption))

        self.confirm = QCheckBox("我已确认视频内容满意,同意发布到所选平台(发布后内容将公开)")
        self.confirm.toggled.connect(self._refresh_button)
        self.open_pages = QCheckBox("导出后同时打开所选平台的上传页面")
        self.export_btn = QPushButton("导出发布包…")
        self.export_btn.setToolTip("不发布,只整理视频和文案,到各平台页面手动上传(不勾选平台则包含全部)")
        self.export_btn.clicked.connect(self._export)
        self.publish_btn = QPushButton("发布")
        self.publish_btn.clicked.connect(self._publish)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        row.addWidget(self.export_btn)
        row.addWidget(self.publish_btn)
        layout.addWidget(self.open_pages)
        layout.addWidget(self.confirm)
        layout.addLayout(row)

        self._refresh_auth()
        self._refresh_button()

    def _region_box(self, region: str, caption: str) -> QGroupBox:
        box = QGroupBox(caption)
        grid = QGridLayout(box)
        for i, p in enumerate(x for x in PLATFORMS if x.region == region):
            check = QCheckBox(p.name)
            check.toggled.connect(self._refresh_button)
            auth_label = QLabel()
            auth_btn = QPushButton()
            auth_btn.clicked.connect(partial(self._toggle_auth, p.id))
            result = QLabel()
            result.setTextInteractionFlags(Qt.TextSelectableByMouse)
            result.setWordWrap(True)
            grid.addWidget(check, i, 0)
            grid.addWidget(auth_label, i, 1)
            grid.addWidget(auth_btn, i, 2)
            grid.addWidget(result, i, 3)
            self._checks[p.id] = check
            self._auth_labels[p.id] = auth_label
            self._auth_buttons[p.id] = auth_btn
            self._result_labels[p.id] = result
        grid.setColumnStretch(3, 1)
        return box

    # --- accounts ----------------------------------------------------------
    def _refresh_auth(self) -> None:
        authorized = self._store.authorized_platforms()
        for pid, check in self._checks.items():
            ok = pid in authorized
            self._auth_labels[pid].setText("已授权" if ok else "未授权")
            self._auth_buttons[pid].setText("解除授权" if ok else "去授权")

    def _toggle_auth(self, platform_id: str, *_) -> None:
        # Placeholder: the real flow opens the platform login / OAuth page.
        now = platform_id in self._store.authorized_platforms()
        self._store.set_authorized(platform_id, not now)
        self._refresh_auth()
        self._refresh_button()

    # --- publishing --------------------------------------------------------
    def selected(self) -> list[str]:
        return [pid for pid, c in self._checks.items() if c.isChecked()]

    def _refresh_button(self) -> None:
        busy = self._worker is not None and self._worker.isRunning()
        selected = self.selected()
        authorized = self._store.authorized_platforms()
        ready = bool(selected) and all(pid in authorized for pid in selected)
        self.publish_btn.setEnabled(self.confirm.isChecked() and ready and not busy)
        self.publish_btn.setToolTip("" if ready or not selected else "所选平台中有未授权的,请先授权,或改用导出发布包")

    def _publish(self) -> None:
        if not self.title.text().strip():
            QMessageBox.warning(self, "提示", "请填写标题。")
            return
        meta = PublishMeta(self.title.text().strip(), self.description.toPlainText().strip(),
                           self.tags.text().split())
        ids = self.selected()
        for pid in ids:
            self._result_labels[pid].setText("")
        self._worker = PublishWorker(self._publisher, ids, self._video_path, meta, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._refresh_button)
        self._worker.start()
        self._refresh_button()

    def _on_progress(self, pid: str, state: str, message: str, url: str) -> None:
        label = self._result_labels[pid]
        if state == "running":
            label.setText("⏳ 发布中…")
            return
        self._store.add_publish(self._task_id, pid, state, message, url)
        label.setText(f"✅ 已发布 {url}" if state == "ok" else f"❌ {message}")

    def meta(self) -> PublishMeta:
        return PublishMeta(self.title.text().strip(), self.description.toPlainText().strip(),
                           self.tags.text().split())

    def export_to(self, out_dir: Path) -> Path:
        folder = export_package(self._video_path, self.meta(), self.selected(), out_dir)
        if self.open_pages.isChecked():
            for pid in self.selected():
                if BY_ID[pid].upload_url:
                    QDesktopServices.openUrl(QUrl(BY_ID[pid].upload_url))
        return folder

    def _export(self) -> None:
        if not self.title.text().strip():
            QMessageBox.warning(self, "提示", "请填写标题。")
            return
        start = self._settings.get("export_dir") if self._settings else ""
        chosen = QFileDialog.getExistingDirectory(self, "选择导出位置", start)
        if not chosen:
            return
        if self._settings:
            self._settings.set("export_dir", chosen)
        folder = self.export_to(Path(chosen))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def done(self, result: int) -> None:
        if self._worker is not None:
            self._worker.wait(5000)
        super().done(result)
