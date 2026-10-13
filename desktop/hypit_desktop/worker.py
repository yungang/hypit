"""Runs an AgentBackend off the UI thread and relays its events as Qt signals."""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from .agent.base import AgentBackend
from .events import Event


class AgentWorker(QThread):
    event = Signal(object)  # Event

    def __init__(self, backend: AgentBackend, brief: dict, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._brief = brief
        self._cv = threading.Condition()
        self._answers: dict[str, str] = {}
        self._cancelled = False

    # --- called from the UI thread -------------------------------------
    def answer(self, confirm_id: str, choice: str) -> None:
        with self._cv:
            self._answers[confirm_id] = choice
            self._cv.notify_all()

    def cancel(self) -> None:
        with self._cv:
            self._cancelled = True
            self._cv.notify_all()

    # --- Responder, called from the agent thread -----------------------
    def wait(self, confirm_id: str) -> Optional[str]:
        with self._cv:
            self._cv.wait_for(lambda: confirm_id in self._answers or self._cancelled)
            return None if self._cancelled else self._answers[confirm_id]

    def sleep(self, seconds: float) -> bool:
        with self._cv:
            self._cv.wait_for(lambda: self._cancelled, timeout=seconds)
            return not self._cancelled

    def run(self) -> None:
        try:
            for ev in self._backend.run(self._brief, self):
                self.event.emit(ev)
        except Exception as exc:  # surface backend failures in the UI
            self.event.emit(Event("error", {"text": f"{type(exc).__name__}: {exc}"}))
