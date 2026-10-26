from __future__ import annotations

from functools import partial
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout)

from .. import money
from ..agent.llm import CUSTOM_LLM, LLM_PRESETS, llm_provider
from ..agent.replay import SCENARIOS
from ..agent.services import GENERATION_CHOICES, unsupported_reason
from ..connection import test_provider
from ..credentials import KeyStore, key_name, stored_or_env
from ..settings import Settings

DIRECTOR, GENERATOR = "director", "generator"


class _TestSignals(QObject):
    done = Signal(str, bool, str)    # which panel, success, message


class _TestJob(QRunnable):
    """A connection check on the thread pool: the dialog must not freeze while the network answers."""

    def __init__(self, role: str, check: Callable[[], tuple[bool, str]], signals: _TestSignals):
        super().__init__()
        self.role, self.check, self.signals = role, check, signals

    def run(self) -> None:
        try:
            ok, text = self.check()
        except Exception as exc:  # noqa: BLE001 - the dialog shows whatever went wrong
            ok, text = False, f"测试时出错:{exc}"
        self.signals.done.emit(self.role, ok, text)


def _password_field() -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText("粘贴 API Key")
    return field


def _label(color: str = "") -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    if color:
        label.setStyleSheet(f"color: {color};")
    return label


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, store: KeyStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(740, 820)
        self._settings, self._store = settings, store
        self._drafts: dict[str, str] = {}      # credential name -> text typed since the dialog opened
        self._signals = _TestSignals(self)
        self._signals.done.connect(self._test_finished)

        # --- AI director -------------------------------------------------------------------------------
        self.llm_provider = QComboBox()
        for key, preset in LLM_PRESETS.items():
            self.llm_provider.addItem(preset.label, key)
        self.llm_provider.addItem(CUSTOM_LLM.label, CUSTOM_LLM.id)
        self.llm_base_url = QLineEdit(settings.get("llm_base_url"))
        self.llm_base_url.setPlaceholderText("兼容 Anthropic 的接口地址,例如 https://api.deepseek.com/anthropic")
        self.llm_model = QLineEdit(settings.get("llm_model"))
        self.llm_model.setPlaceholderText("模型名,例如 deepseek-flash")
        self.llm_key = _password_field()
        self.llm_status = _label()
        self.llm_notice = _label("#b26a00")
        llm_test = QPushButton("测试连接")
        llm_test.clicked.connect(self._test_llm)
        llm_clear = QPushButton("清空密钥")
        llm_clear.clicked.connect(self._clear_llm_key)
        llm_buttons = QHBoxLayout()
        llm_buttons.addWidget(llm_test)
        llm_buttons.addWidget(llm_clear)
        llm_buttons.addStretch()
        llm_form = QFormLayout()
        llm_form.addRow("服务商", self.llm_provider)
        llm_form.addRow("接口地址", self.llm_base_url)
        llm_form.addRow("模型", self.llm_model)
        llm_form.addRow("API Key", self.llm_key)
        llm_form.addRow("", llm_buttons)
        llm_form.addRow("", self.llm_status)
        llm_form.addRow("", self.llm_notice)
        llm_box = QGroupBox("AI 导演(负责看参考视频、写脚本)")
        llm_box.setLayout(llm_form)

        # --- video and image generation ---------------------------------------------------------------
        self.service = QComboBox()
        for service_id, label, _env in GENERATION_CHOICES:
            self.service.addItem(label, service_id)
        if settings.get("generation_service") == "hypihub":          # the old path stays reachable for developers
            self.service.addItem("HypiHub(旧方案,开发用,需先在命令行登录)", "hypihub")
        self.gen_key = _password_field()
        self.gen_status = _label()
        self.gen_notice = _label("#b26a00")
        self.gen_test = QPushButton("测试连接")
        self.gen_test.clicked.connect(self._test_generator)
        self.gen_clear = QPushButton("清空密钥")
        self.gen_clear.clicked.connect(self._clear_generator_key)
        gen_buttons = QHBoxLayout()
        gen_buttons.addWidget(self.gen_test)
        gen_buttons.addWidget(self.gen_clear)
        gen_buttons.addStretch()
        self.whisperx_home = QLineEdit(settings.get("whisperx_home"))
        self.whisperx_home.setPlaceholderText("留空使用安装目录下的 services\\whisperx(包含 .venv 的文件夹)")
        self.whisperx_browse = QPushButton("浏览…")
        self.whisperx_browse.clicked.connect(self._browse_whisperx)
        whisperx_row = QHBoxLayout()
        whisperx_row.addWidget(self.whisperx_home, 1)
        whisperx_row.addWidget(self.whisperx_browse)
        gen_form = QFormLayout()
        gen_form.addRow("服务商", self.service)
        gen_form.addRow("API Key", self.gen_key)
        gen_form.addRow("", gen_buttons)
        gen_form.addRow("", self.gen_status)
        gen_form.addRow("", self.gen_notice)
        gen_form.addRow("本地语音对齐服务", whisperx_row)
        gen_box = QGroupBox("视频和图片生成(费用直接付给服务商)")
        gen_box.setLayout(gen_form)

        # --- general ---------------------------------------------------------------------------------
        self.export_dir = QLineEdit(settings.get("export_dir"))
        self.export_dir.setPlaceholderText("每次导出时询问")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.export_dir, 1)
        dir_row.addWidget(browse)
        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 8)
        self.concurrent.setValue(int(settings.get("max_concurrent")))
        self.concurrent.setToolTip("同时执行的任务数;超出的在执行队列里排队")
        self.backend = QComboBox()
        self.backend.addItem("演示回放(不联网,不花钱)", "replay")
        self.backend.addItem("AI 导演 + 真实生成(按所选服务商计费)", "agent")
        self.backend.addItem("Hypit 固定示例(开发用,会扣 HypiHub 积分)", "hypit")
        self.backend.setCurrentIndex(max(0, self.backend.findData(settings.get("backend"))))
        self.currency = QComboBox()
        for code, label in money.CURRENCIES.items():
            self.currency.addItem(label, code)
        self.currency.setCurrentIndex(max(0, self.currency.findData(settings.get("display_currency"))))
        general = QFormLayout()
        general.addRow("生成方式", self.backend)
        general.addRow("费用显示币种", self.currency)
        general.addRow("同时执行任务数", self.concurrent)
        general.addRow("发布包默认导出位置", dir_row)
        general_box = QGroupBox("常规")
        general_box.setLayout(general)

        # --- development ------------------------------------------------------------------------------
        self.llm_key_env = QLineEdit(settings.get("llm_key_env"))
        self.llm_key_env.setPlaceholderText("DeepSeek 没有保存密钥时改用这个环境变量,默认 DEEPSEEK_API_KEY")
        self.launcher = QLineEdit(settings.get("hypit_launcher"))
        self.launcher.setPlaceholderText("Hypit 启动文件 hypit.mjs(留空用默认位置)")
        self.use_proxy = QCheckBox("Hypit 联网时使用系统代理环境变量(HTTPS_PROXY 等)")
        self.use_proxy.setChecked(bool(settings.get("use_env_proxy")))
        self.project_dir = QLineEdit(settings.get("hypit_project_dir"))
        self.project_dir.setPlaceholderText("直接使用已有的 Hypit 项目目录(留空则按模板新建)")
        self.run_source = QLineEdit(settings.get("hypit_run_source"))
        self.run_source.setPlaceholderText("运行文件,默认 reference.svrun")
        self.scenario = QComboBox()
        for sid, (label, _) in SCENARIOS.items():
            self.scenario.addItem(label, sid)
        self.scenario.setCurrentIndex(max(0, self.scenario.findData(settings.get("scenario"))))
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 20)
        self.speed.setSingleStep(0.5)
        self.speed.setValue(float(settings.get("replay_speed")))
        dev = QFormLayout()
        dev.addRow("备用密钥环境变量", self.llm_key_env)
        dev.addRow("Hypit 启动文件", self.launcher)
        dev.addRow("", self.use_proxy)
        dev.addRow("项目目录", self.project_dir)
        dev.addRow("运行文件", self.run_source)
        dev.addRow("演示场景", self.scenario)
        dev.addRow("演示播放速度", self.speed)
        self.dev_box = QGroupBox("开发选项")
        self.dev_box.setCheckable(True)
        self.dev_box.setChecked(False)
        self.dev_box.setLayout(dev)

        ok = QPushButton("保存")
        ok.clicked.connect(self._save)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addWidget(llm_box)
        layout.addWidget(gen_box)
        layout.addWidget(general_box)
        layout.addWidget(self.dev_box)
        layout.addStretch()
        layout.addLayout(buttons)

        self.llm_provider.setCurrentIndex(max(0, self.llm_provider.findData(settings.get("llm_provider"))))
        self.service.setCurrentIndex(max(0, self.service.findData(settings.get("generation_service"))))
        self.llm_provider.currentIndexChanged.connect(self._llm_provider_changed)
        self.service.currentIndexChanged.connect(self._service_changed)
        self.llm_key.textEdited.connect(self._llm_key_edited)
        self.gen_key.textEdited.connect(self._gen_key_edited)
        self._llm_provider_changed()
        self._service_changed()

    # --- which provider / which credential --------------------------------------------------------------
    def _llm_id(self) -> str:
        return self.llm_provider.currentData()

    def _gen_id(self) -> str:
        return self.service.currentData()

    def _llm_env(self) -> str:
        preset = LLM_PRESETS.get(self._llm_id())
        if preset is None:
            return ""
        return self._settings.get("llm_key_env") if preset.id == "deepseek" else preset.env_var

    def _gen_env(self) -> str:
        return next((env for sid, _label_text, env in GENERATION_CHOICES if sid == self._gen_id()), "")

    def _llm_endpoint(self) -> tuple[str, str]:
        preset = LLM_PRESETS.get(self._llm_id())
        if preset is not None:
            return preset.base_url, preset.model
        return self.llm_base_url.text().strip(), self.llm_model.text().strip()

    # --- keys: filled in from the Credential Manager when a provider is chosen --------------------------
    def _store_value(self, name: str) -> str:
        try:
            return self._store.get(name)
        except OSError:
            return ""

    def _show_key(self, field: QLineEdit, status: QLabel, provider_id: str, env_var: str) -> None:
        """Put the provider's key in the field (a saved one, or what was typed here and not saved yet)."""
        name = key_name(provider_id)
        field.setText(self._drafts[name] if name in self._drafts else self._store_value(name))
        if name in self._drafts and self._drafts[name] != self._store_value(name):
            status.setText("密钥已修改,保存后生效。" if self._drafts[name] else "保存后会清除这个服务商的密钥。")
        elif field.text():
            status.setText("已保存的密钥已自动填入。")
        elif env_var and stored_or_env(None, name, env_var):
            status.setText(f"没有保存密钥,当前使用环境变量 {env_var}。")
        else:
            status.setText("还没有设置密钥。")
        status.setStyleSheet("")

    def _refresh_other_panel(self, edited: str) -> None:
        """One provider can serve as director and as generator at once; the two fields show the same key."""
        panels = ((DIRECTOR, self.llm_key, self.llm_status, self._llm_id(), self._llm_env()),
                  (GENERATOR, self.gen_key, self.gen_status, self._gen_id(), self._gen_env()))
        for role, field, status, provider_id, env_var in panels:
            if role != edited and key_name(provider_id) == key_name(self._llm_id() if edited == DIRECTOR else self._gen_id()):
                self._show_key(field, status, provider_id, env_var)

    def _llm_key_edited(self, text: str) -> None:
        self._drafts[key_name(self._llm_id())] = text
        self.llm_status.setText("密钥已修改,保存后生效。" if text else "保存后会清除这个服务商的密钥。")
        self.llm_status.setStyleSheet("")
        self._refresh_other_panel(DIRECTOR)

    def _gen_key_edited(self, text: str) -> None:
        self._drafts[key_name(self._gen_id())] = text
        self.gen_status.setText("密钥已修改,保存后生效。" if text else "保存后会清除这个服务商的密钥。")
        self.gen_status.setStyleSheet("")
        self._refresh_other_panel(GENERATOR)

    def _llm_provider_changed(self, *_) -> None:
        provider = llm_provider(self._llm_id())
        if provider.id != "custom":
            self.llm_base_url.setText(provider.base_url)
            self.llm_model.setText(provider.model)
        custom = provider.id == "custom"
        self.llm_base_url.setEnabled(custom)
        self.llm_model.setEnabled(custom)
        self.llm_notice.setText(provider.note)
        self._show_key(self.llm_key, self.llm_status, provider.id, self._llm_env())

    def _service_changed(self, *_) -> None:
        service_id = self._gen_id()
        self.gen_notice.setText(unsupported_reason(service_id))
        ark = service_id == "ark"
        self.whisperx_home.setEnabled(ark)
        self.whisperx_browse.setEnabled(ark)
        has_key = service_id != "hypihub"        # HypiHub signs in on the command line, not with a key typed here
        for widget in (self.gen_key, self.gen_test, self.gen_clear):
            widget.setEnabled(has_key)
        self._show_key(self.gen_key, self.gen_status, service_id, self._gen_env())

    # --- connection tests -------------------------------------------------------------------------------
    def _key_for_test(self, field: QLineEdit, provider_id: str, env_var: str) -> str:
        return field.text().strip() or stored_or_env(self._store, key_name(provider_id), env_var)

    def _start_test(self, role: str, status: QLabel, check: Callable[[], tuple[bool, str]]) -> None:
        status.setText("正在测试…")
        status.setStyleSheet("")
        QThreadPool.globalInstance().start(_TestJob(role, check, self._signals))

    def _test_llm(self, *_) -> None:
        base_url, model = self._llm_endpoint()
        key = self._key_for_test(self.llm_key, self._llm_id(), self._llm_env())
        self._start_test(DIRECTOR, self.llm_status, partial(test_provider, self._llm_id(), key, base_url, model))

    def _test_generator(self, *_) -> None:
        key = self._key_for_test(self.gen_key, self._gen_id(), self._gen_env())
        self._start_test(GENERATOR, self.gen_status, partial(test_provider, self._gen_id(), key))

    def _test_finished(self, role: str, ok: bool, text: str) -> None:
        status = self.llm_status if role == DIRECTOR else self.gen_status
        status.setText(("✓ " if ok else "✗ ") + text)
        status.setStyleSheet("color: #1a7f37;" if ok else "color: #c62828;")

    def _clear_llm_key(self, *_) -> None:
        self.llm_key.clear()
        self._llm_key_edited("")

    def _clear_generator_key(self, *_) -> None:
        self.gen_key.clear()
        self._gen_key_edited("")

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择默认导出位置", self.export_dir.text())
        if chosen:
            self.export_dir.setText(chosen)

    def _browse_whisperx(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择语音对齐服务文件夹(包含 .venv)", self.whisperx_home.text())
        if chosen:
            self.whisperx_home.setText(chosen)

    # --- saving -------------------------------------------------------------------------------------------
    def _save_keys(self) -> None:
        for name, text in self._drafts.items():
            text = text.strip()
            if text:
                self._store.set(name, text)
            elif self._store_value(name):
                self._store.delete(name)

    def _save(self) -> None:
        try:
            self._save_keys()
        except OSError as exc:
            QMessageBox.warning(self, "保存密钥失败", str(exc))
            return
        base_url, model = self._llm_endpoint()
        self._settings.set("llm_provider", self._llm_id())
        self._settings.set("llm_base_url", base_url)
        self._settings.set("llm_model", model or "deepseek-flash")
        self._settings.set("generation_service", self._gen_id())
        self._settings.set("whisperx_home", self.whisperx_home.text().strip())
        self._settings.set("display_currency", self.currency.currentData())
        money.configure(self.currency.currentData())
        self._settings.set("backend", self.backend.currentData())
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
