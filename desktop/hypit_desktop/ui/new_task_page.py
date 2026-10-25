from __future__ import annotations

import threading
from functools import partial
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import media_info
from ..briefs import (ASPECTS, DEFAULTS, DURATION_PRESETS, IMAGE_KEYS, LANGUAGES, MARKETS, MODELS,
                      RESOLUTIONS, TEMPLATE_KEYS, image_problems, normalize)
from ..db import TaskStore
from ..video_title import fallback_title, fetch_title
from .featured import FeaturedStrip
from .featured_dialog import FeaturedDialog
from .replace_table import ReplaceTable

# Development convenience: prefilled so tests need no typing. Clear before wider rollout.
DEFAULT_URL = "https://www.douyin.com/video/7684610633048342905"
BATCH_CONFIRM_THRESHOLD = 10


class TitleBridge(QObject):
    """Carries a fetched title from a background thread back to the UI thread."""
    ready = Signal(str, str)  # url, title ('' when unreadable)


class NewTaskPage(QWidget):
    # briefs, destination ("waiting" = run queue, "pending" = to-do queue), edited task id or None
    submitted = Signal(list, str, object)

    def __init__(self, store: TaskStore, title_fetcher: Optional[Callable[[str], Optional[str]]] = fetch_title):
        super().__init__()
        self._store = store
        self._fetch = title_fetcher       # None disables reading titles from the web
        self._titles: dict[str, str] = {}  # url -> title read from the web
        self._edit_id: int | None = None
        self._source_info = ""
        self._bridge = TitleBridge(self)
        self._bridge.ready.connect(self._on_title)

        self._title = QLabel("复刻一条视频")
        self._title.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.simple_radio = QRadioButton("简单模式")
        self.pro_radio = QRadioButton("专业模式")
        self.simple_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.simple_radio)
        mode_group.addButton(self.pro_radio)
        self.pro_radio.toggled.connect(self._on_mode)
        head = QHBoxLayout()
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(self.simple_radio)
        head.addWidget(self.pro_radio)

        self.featured = FeaturedStrip(store)
        self.featured.picked.connect(self.apply_featured)
        self.featured.manage_requested.connect(self._manage_featured)

        # --- source ---
        self.url_radio = QRadioButton("视频链接")
        self.file_radio = QRadioButton("本地文件")
        self.url_radio.setChecked(True)
        source_group = QButtonGroup(self)
        source_group.addButton(self.url_radio)
        source_group.addButton(self.file_radio)
        self.url = QLineEdit(DEFAULT_URL)
        self.url.setPlaceholderText("https://...")
        self.url.editingFinished.connect(self._on_url_done)
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("选择本地视频文件")
        self.file_path.setReadOnly(True)
        pick_file = QPushButton("选择文件…")
        pick_file.clicked.connect(self._pick_file)
        self.file_radio.toggled.connect(self._on_source)
        self._info = QLabel("")
        self._info.setStyleSheet("color: #666;")
        source_row = QHBoxLayout()
        source_row.addWidget(self.url_radio)
        source_row.addWidget(self.file_radio)
        source_row.addStretch()
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_path, 1)
        file_row.addWidget(pick_file)
        self._file_box = QWidget()
        self._file_box.setLayout(file_row)
        file_row.setContentsMargins(0, 0, 0, 0)
        self._file_box.hide()

        # --- one row per clone task ---
        self.table = ReplaceTable()
        self.table.rows_changed.connect(self._update_count)
        add_row = QPushButton("＋ 添加一行")
        add_row.clicked.connect(self._add_row)
        remove_rows = QPushButton("删除所选行")
        remove_rows.clicked.connect(self._remove_rows)
        table_hint = QLabel("每行一个复刻任务。角色、商品、背景图片都可不填(不填就沿用原视频);双击图片格选择,右键清除。")
        table_hint.setStyleSheet("color: #666;")
        table_hint.setWordWrap(True)
        table_bar = QHBoxLayout()
        table_bar.addWidget(add_row)
        table_bar.addWidget(remove_rows)
        table_bar.addStretch()
        table_box = QVBoxLayout()
        table_box.addLayout(table_bar)
        table_box.addWidget(self.table)
        table_box.addWidget(table_hint)

        # --- common parameters ---
        self.market = QComboBox()
        self.market.addItems(MARKETS)
        self.market.setEditable(True)
        self.language = QComboBox()
        self.language.addItems(LANGUAGES)
        self.language.setEditable(True)
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self.aspect = QComboBox()
        self.aspect.addItems(ASPECTS)
        self.resolution = QComboBox()
        self.resolution.addItems(RESOLUTIONS)
        self.resolution.setCurrentText(DEFAULTS["resolution"])
        self.fixed_radio = QRadioButton("固定")
        self.custom_radio = QRadioButton("自定义")
        self.fixed_radio.setChecked(True)
        dur_group = QButtonGroup(self)
        dur_group.addButton(self.fixed_radio)
        dur_group.addButton(self.custom_radio)
        self.duration_preset = QComboBox()
        for sec in DURATION_PRESETS:
            self.duration_preset.addItem(f"{sec} 秒", sec)
        self.duration_preset.setCurrentIndex(DURATION_PRESETS.index(15))
        self.duration_custom = QSpinBox()
        self.duration_custom.setRange(1, 600)
        self.duration_custom.setValue(15)
        self.duration_custom.setSuffix(" 秒")
        self.duration_custom.setEnabled(False)
        self.custom_radio.toggled.connect(self._on_duration_kind)
        duration_row = QHBoxLayout()
        for w in (self.fixed_radio, self.duration_preset, self.custom_radio, self.duration_custom):
            duration_row.addWidget(w)
        duration_row.addStretch()

        form = QFormLayout()
        form.addRow("参考视频", source_row)
        form.addRow("", self.url)
        form.addRow("", self._file_box)
        form.addRow("", self._info)
        form.addRow("复刻任务", table_box)
        form.addRow("目标市场", self.market)
        form.addRow("目标语言", self.language)
        form.addRow("模型", self.model)
        form.addRow("画面比例", self.aspect)
        form.addRow("分辨率", self.resolution)
        form.addRow("时长", duration_row)

        # --- professional-only fields ---
        self.scene = QLineEdit()
        self.scene.setPlaceholderText("例如:办公室、街头采访、居家")
        self.extra_prompt = QPlainTextEdit()
        self.extra_prompt.setPlaceholderText("补充提示词:想强调的风格、必须出现或避免的内容……")
        self.extra_prompt.setFixedHeight(80)
        self.preview_first = QCheckBox("先出分镜/样片,确认后再正式生成")
        self.template_combo = QComboBox()
        self.template_combo.activated.connect(self._apply_template)
        save_template = QPushButton("保存为模板…")
        save_template.clicked.connect(self._save_template)
        delete_template = QPushButton("删除模板")
        delete_template.clicked.connect(self._delete_template)
        template_row = QHBoxLayout()
        template_row.addWidget(self.template_combo, 1)
        template_row.addWidget(save_template)
        template_row.addWidget(delete_template)

        pro_form = QFormLayout()
        pro_form.addRow("模板", template_row)
        pro_form.addRow("场景", self.scene)
        pro_form.addRow("补充提示词", self.extra_prompt)
        pro_form.addRow("", self.preview_first)
        self._pro_box = QWidget()
        self._pro_box.setLayout(pro_form)
        pro_form.setContentsMargins(0, 0, 0, 0)
        self._pro_box.hide()

        # --- actions ---
        self._count = QLabel("")
        self._count.setStyleSheet("color: #666;")
        self._notice = QLabel("")
        self._notice.setStyleSheet("color: #2a7a2a;")
        self.run_btn = QPushButton("加入执行队列")
        self.run_btn.setStyleSheet("padding: 8px 20px; font-size: 14px;")
        self.run_btn.clicked.connect(partial(self._submit, "waiting"))
        self.queue_btn = QPushButton("加入待执行队列")
        self.queue_btn.setStyleSheet("padding: 8px 20px; font-size: 14px;")
        self.queue_btn.clicked.connect(partial(self._submit, "pending"))
        actions = QHBoxLayout()
        actions.addWidget(self.run_btn)
        actions.addWidget(self.queue_btn)
        actions.addWidget(self._count)
        actions.addStretch()

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addLayout(head)
        layout.addWidget(self.featured)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addWidget(self._pro_box)
        layout.addSpacing(8)
        layout.addLayout(actions)
        layout.addWidget(self._notice)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._refresh_templates()
        self.reset_rows()

    # --- modes ---------------------------------------------------------------------
    def is_pro(self) -> bool:
        return self.pro_radio.isChecked()

    def _on_mode(self, pro: bool) -> None:
        self._pro_box.setVisible(pro)

    def _on_source(self, is_file: bool) -> None:
        self.url.setVisible(not is_file)
        self._file_box.setVisible(is_file)
        self._info.setText(self._source_info if is_file else "")
        self._refresh_default()

    def _on_duration_kind(self, custom: bool) -> None:
        self.duration_custom.setEnabled(custom)
        self.duration_preset.setEnabled(not custom)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择参考视频", "", "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)")
        if not path:
            return
        self.file_path.setText(path)
        info = media_info.probe(path)
        self._source_info = media_info.describe(info) if info else "(未能读取视频信息)"
        self._info.setText(self._source_info)
        self._refresh_default()

    # --- default theme: file name, web page title, or '<platform>_<video id>' -------------
    def _source_default(self) -> str:
        if self.file_radio.isChecked():
            path = self.file_path.text().strip()
            return Path(path).stem if path else ""
        url = self.url.text().strip()
        return self._titles.get(url) or (fallback_title(url) if url else "")

    def _refresh_default(self) -> None:
        self.table.set_default_topic(self._source_default())

    def _on_url_done(self) -> None:
        self._refresh_default()
        self._request_title(self.url.text().strip())

    def _request_title(self, url: str) -> None:
        if self._fetch is None or url in self._titles or not url.lower().startswith(("http://", "https://")):
            return
        threading.Thread(target=self._fetch_title_worker, args=(url,), daemon=True).start()

    def _fetch_title_worker(self, url: str) -> None:
        try:
            title = self._fetch(url) or ""
        except Exception:
            title = ""
        try:
            self._bridge.ready.emit(url, title)
        except RuntimeError:
            pass  # the page was closed while the request was running

    def _on_title(self, url: str, title: str) -> None:
        if not title:
            return
        self._titles[url] = title
        if not self.file_radio.isChecked() and url == self.url.text().strip():
            self._refresh_default()

    # --- rows ------------------------------------------------------------------------------
    def _add_row(self, *_) -> None:
        self.table.add_row(self._source_default())

    def _remove_rows(self, *_) -> None:
        self.table.remove_selected_rows()

    def reset_rows(self) -> None:
        """One empty row carrying the default theme (also clears a previous batch)."""
        self.table.reset(self._source_default())

    def _update_count(self) -> None:
        n = self.table.rowCount()
        self._count.setText(f"将创建 {n} 个任务" if n > 1 else "")

    # --- reading and filling the form -----------------------------------------------------------
    def _duration_text(self) -> str:
        seconds = self.duration_custom.value() if self.custom_radio.isChecked() else self.duration_preset.currentData()
        return f"{seconds} 秒"

    def _base(self) -> dict:
        brief = dict(DEFAULTS)
        is_file = self.file_radio.isChecked()
        brief.update(
            mode="pro" if self.is_pro() else "simple",
            source_type="file" if is_file else "url",
            url=self.file_path.text().strip() if is_file else self.url.text().strip(),
            source_info=self._source_info if is_file else "",
            market=self.market.currentText().strip(), language=self.language.currentText().strip(),
            model=self.model.currentText(), aspect=self.aspect.currentText(),
            resolution=self.resolution.currentText(), duration=self._duration_text())
        if self.is_pro():
            brief.update(scene=self.scene.text().strip(),
                         extra_prompt=self.extra_prompt.toPlainText().strip(),
                         preview_first=self.preview_first.isChecked())
        return brief

    def collect(self) -> list[dict]:
        base = self._base()
        if base["source_type"] == "url":
            if not base["url"].lower().startswith(("http://", "https://")):
                raise ValueError("请填写以 http(s):// 开头的视频链接。")
        elif not Path(base["url"]).is_file():
            raise ValueError("请选择一个存在的本地视频文件。")
        rows = self.table.rows()
        if not rows:
            raise ValueError("请至少保留一行复刻任务。")
        default = self._source_default() or "未命名"
        briefs = []
        for number, row in enumerate(rows, 1):
            brief = {**base, "topic": row["topic"] or default, **{key: row[key] for key, _ in IMAGE_KEYS}}
            missing = image_problems(brief)
            if missing:
                raise ValueError(f"第 {number} 行的{'、'.join(missing)}图片文件不存在,请重新选择。")
            briefs.append(brief)
        return briefs

    def apply_params(self, params: dict) -> None:
        """Set only the parameters present in `params` (featured entries, templates)."""
        def set_combo(combo: QComboBox, value: str) -> None:
            index = combo.findText(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            elif combo.isEditable():
                combo.setCurrentText(value)

        if "scene" in params:
            self.scene.setText(params["scene"])
        if "market" in params:
            set_combo(self.market, params["market"])
        if "language" in params:
            set_combo(self.language, params["language"])
        if "model" in params:
            set_combo(self.model, params["model"])
        if "aspect" in params:
            set_combo(self.aspect, params["aspect"])
        if "resolution" in params:
            set_combo(self.resolution, params["resolution"])
        if "extra_prompt" in params:
            self.extra_prompt.setPlainText(params["extra_prompt"])
        if "preview_first" in params:
            self.preview_first.setChecked(bool(params["preview_first"]))
        if "duration" in params:
            digits = "".join(ch for ch in params["duration"] if ch.isdigit())
            seconds = int(digits) if digits else 0
            if seconds in DURATION_PRESETS:
                self.fixed_radio.setChecked(True)
                self.duration_preset.setCurrentIndex(DURATION_PRESETS.index(seconds))
            elif seconds > 0:
                self.custom_radio.setChecked(True)
                self.duration_custom.setValue(seconds)

    def fill(self, brief: dict) -> None:
        """Show one saved brief (editing a queued task)."""
        b = normalize(brief)
        (self.pro_radio if b["mode"] == "pro" else self.simple_radio).setChecked(True)
        if b["source_type"] == "file":
            self.file_radio.setChecked(True)
            self.file_path.setText(b["url"])
            self._source_info = b["source_info"]
            self._info.setText(self._source_info)
        else:
            self.url_radio.setChecked(True)
            self.url.setText(b["url"])
        self.table.load_rows([{"topic": b["topic"], **{key: b[key] for key, _ in IMAGE_KEYS}}])
        self.apply_params({k: b[k] for k in TEMPLATE_KEYS})

    def apply_featured(self, entry: dict) -> None:
        self.url_radio.setChecked(True)
        self.url.setText(entry["url"])
        self.apply_params(entry["params"])
        self._titles.setdefault(entry["url"], entry["title"])  # the card already names the video
        self._refresh_default()
        self._notice.setText(f"已套用「{entry['title']}」的链接和参数,可按需添加替换图片后提交。")

    def _manage_featured(self) -> None:
        FeaturedDialog(self._store, self).exec()
        self.featured.refresh()

    # --- templates ---------------------------------------------------------------------------------
    def _refresh_templates(self, select: str = "") -> None:
        self.template_combo.clear()
        self.template_combo.addItem("(不使用模板)", "")
        for name in self._store.templates():
            self.template_combo.addItem(name, name)
        index = self.template_combo.findData(select)
        self.template_combo.setCurrentIndex(max(0, index))

    def template_params(self) -> dict:
        b = self._base()
        b.update(scene=self.scene.text().strip(), extra_prompt=self.extra_prompt.toPlainText().strip(),
                 preview_first=self.preview_first.isChecked())
        return {k: b[k] for k in TEMPLATE_KEYS}

    def _apply_template(self, index: int) -> None:
        name = self.template_combo.itemData(index)
        if name:
            self.apply_params(self._store.templates()[name])

    def _save_template(self) -> None:
        name, ok = QInputDialog.getText(self, "保存为模板", "模板名称(同名会覆盖)")
        name = name.strip()
        if not ok or not name:
            return
        self._store.save_template(name, self.template_params())
        self._refresh_templates(select=name)

    def _delete_template(self) -> None:
        name = self.template_combo.currentData()
        if not name:
            return
        if QMessageBox.question(self, "删除模板", f"确定删除模板「{name}」吗?") != QMessageBox.Yes:
            return
        self._store.delete_template(name)
        self._refresh_templates()

    # --- submit / edit mode ------------------------------------------------------------------------------
    def set_edit(self, task_id: int, brief: dict) -> None:
        self._edit_id = task_id
        self._title.setText("编辑待执行任务")
        self.run_btn.setText("保存并加入执行队列")
        self.queue_btn.setText("保存修改")
        self._notice.setText("")
        self.fill(brief)

    def set_new(self, notice: str = "") -> None:
        if self._edit_id is not None:  # leaving edit mode: do not keep showing the edited task
            self.reset_rows()
        self._edit_id = None
        self._title.setText("复刻一条视频")
        self.run_btn.setText("加入执行队列")
        self.queue_btn.setText("加入待执行队列")
        self._notice.setText(notice)

    def _submit(self, destination: str, *_) -> None:
        try:
            briefs = self.collect()
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        if len(briefs) > BATCH_CONFIRM_THRESHOLD and QMessageBox.question(
                self, "批量创建", f"将创建 {len(briefs)} 个任务,确定吗?") != QMessageBox.Yes:
            return
        self.submitted.emit(briefs, destination, self._edit_id)
