from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..events import Event

STEP_ICONS = {"running": "⏳", "done": "✅", "failed": "❌"}


class ConfirmCard(QFrame):
    answered = Signal(str, str)  # confirm id, choice

    def __init__(self, data: dict):
        super().__init__()
        self.confirm_id = data["id"]
        self.setStyleSheet("ConfirmCard { background: #fff7e6; border: 1px solid #ffd591; border-radius: 8px; }")
        self._prompt = QLabel(data["prompt"])
        self._prompt.setWordWrap(True)
        self._buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout()
        for opt in data["options"]:
            btn = QPushButton(opt["label"])
            btn.clicked.connect(partial(self._click, opt["id"]))
            self._buttons[opt["id"]] = btn
            row.addWidget(btn)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(self._prompt)
        layout.addLayout(row)

    def _click(self, choice: str, *_) -> None:
        self.lock(choice)
        self.answered.emit(self.confirm_id, choice)

    def lock(self, choice: str) -> None:
        for opt_id, btn in self._buttons.items():
            btn.setEnabled(False)
            if opt_id == choice:
                btn.setText("✔ " + btn.text().lstrip("✔ "))


class VideoPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._video = QVideoWidget()
        self._video.setMinimumHeight(220)
        self._audio = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._note = QLabel()
        self._note.setAlignment(Qt.AlignCenter)
        self._toggle = QPushButton("播放 / 暂停")
        self._toggle.clicked.connect(self._toggle_play)
        layout = QVBoxLayout(self)
        layout.addWidget(self._video)
        layout.addWidget(self._note)
        layout.addWidget(self._toggle)

    def load(self, path: str) -> None:
        file = Path(path)
        if file.is_file():
            self._note.setText(file.name)
            self._player.setSource(QUrl.fromLocalFile(str(file.resolve())))
        else:
            self._note.setText(f"(演示数据:{path} 不存在,正式版这里会播放渲染结果)")
            self._toggle.setEnabled(False)

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def stop(self) -> None:
        self._player.stop()


class TaskPage(QWidget):
    confirm_answered = Signal(str, str)
    cancel_requested = Signal()
    publish_requested = Signal(str)  # video path
    rerun_requested = Signal()
    runs_requested = Signal()

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.video_path = ""
        self._header = QLabel(title)
        self._header.setStyleSheet("font-size: 18px; font-weight: 600;")
        sub = QLabel(subtitle)
        sub.setStyleSheet("color: #666;")
        sub.setWordWrap(True)
        sub.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._steps = QListWidget()
        self._steps.setMaximumHeight(150)
        self._step_items: dict[str, QListWidgetItem] = {}

        self._chat = QVBoxLayout()
        self._chat.setAlignment(Qt.AlignTop)
        body = QWidget()
        body.setLayout(self._chat)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(body)
        self._scroll.verticalScrollBar().rangeChanged.connect(self._scroll_to_end)

        self._video = VideoPanel()
        self._video.hide()

        self._cost = QLabel("本次 $0.00 · 累计 $0.00")
        self._runs_btn = QPushButton("运行记录…")
        self._runs_btn.clicked.connect(self.runs_requested)
        self._status = QLabel("")
        self._cancel = QPushButton("取消任务")
        self._cancel.clicked.connect(self.cancel_requested)
        self._rerun = QPushButton("重新运行")
        self._rerun.hide()
        self._rerun.clicked.connect(self.rerun_requested)
        self._publish = QPushButton("满意,去发布…")
        self._publish.hide()
        self._publish.clicked.connect(self._emit_publish)
        footer = QHBoxLayout()
        footer.addWidget(self._cost)
        footer.addWidget(self._runs_btn)
        footer.addWidget(self._status)
        footer.addStretch()
        footer.addWidget(self._cancel)
        footer.addWidget(self._rerun)
        footer.addWidget(self._publish)

        layout = QVBoxLayout(self)
        layout.addWidget(self._header)
        layout.addWidget(sub)
        layout.addWidget(self._steps)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._video)
        layout.addLayout(footer)

        self._cards: dict[str, ConfirmCard] = {}

    def _scroll_to_end(self, _lo: int, hi: int) -> None:
        self._scroll.verticalScrollBar().setValue(hi)

    def _emit_publish(self, *_) -> None:
        self.publish_requested.emit(self.video_path)

    def set_costs(self, current: float, total: float, runs: int) -> None:
        self._cost.setText(f"本次 ${current:.2f} · 累计 ${total:.2f}(共 {runs} 次运行)")

    def set_waiting(self) -> None:
        self._cancel.hide()
        self._status.setText("排队中,等待空闲名额")

    def set_running(self) -> None:
        self._cancel.show()
        self._rerun.hide()
        self._status.setText("")

    def set_title(self, title: str) -> None:
        self._header.setText(title)

    def set_finished(self, label: str, can_rerun: bool = True) -> None:
        self._cancel.hide()
        self._status.setText(label)
        self._rerun.setVisible(can_rerun)

    def apply_event(self, ev: Event) -> None:
        d = ev.data
        if ev.type == "step":
            text = f"{STEP_ICONS.get(d['state'], '•')}  {d['title']}"
            item = self._step_items.get(d["id"])
            if item is None:
                item = QListWidgetItem()
                self._steps.addItem(item)
                self._step_items[d["id"]] = item
            item.setText(text)
            self._steps.scrollToItem(item)
        elif ev.type == "message":
            self._add_bubble(d["text"], agent=d.get("role") == "agent")
        elif ev.type == "confirm":
            card = ConfirmCard(d)
            card.answered.connect(self.confirm_answered)
            self._cards[d["id"]] = card
            self._chat.addWidget(card)
        elif ev.type == "answer":
            card = self._cards.get(d["id"])
            if card:
                card.lock(d["choice"])
            self._add_bubble(f"我的选择:{d['label']}", agent=False)
        elif ev.type == "cost":
            pass  # amounts come from the run ledger via set_costs
        elif ev.type == "artifact" and d.get("kind") == "video":
            self.video_path = d["path"]
            self._video.load(d["path"])
            self._video.show()
        elif ev.type == "error":
            self._add_bubble("出错了:" + d["text"], agent=True)
            self.set_finished("失败")
        elif ev.type == "done":
            if d["status"] == "success" and self.video_path:
                self._publish.show()
            self.set_finished({"success": "已完成", "cancelled": "已取消"}.get(d["status"], d["status"]),
                              can_rerun=d["status"] != "success")

    def _add_bubble(self, text: str, agent: bool) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setMinimumWidth(320)
        label.setMaximumWidth(720)
        label.setStyleSheet(
            "padding: 8px 12px; border-radius: 8px; background: %s;" % ("#f0f2f5" if agent else "#d9ecff"))
        row = QHBoxLayout()
        if not agent:
            row.addStretch()
        row.addWidget(label, 0)
        if agent:
            row.addStretch()
        holder = QWidget()
        holder.setLayout(row)
        self._chat.addWidget(holder)
