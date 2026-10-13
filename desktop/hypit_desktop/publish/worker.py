from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .base import PublishError, PublishMeta, Publisher


class PublishWorker(QThread):
    progress = Signal(str, str, str, str)  # platform id, state (running|ok|failed), message, url

    def __init__(self, publisher: Publisher, platform_ids: list[str], video_path: str,
                 meta: PublishMeta, parent=None):
        super().__init__(parent)
        self._publisher = publisher
        self._platform_ids = platform_ids
        self._video_path = video_path
        self._meta = meta

    def run(self) -> None:
        for pid in self._platform_ids:
            self.progress.emit(pid, "running", "", "")
            try:
                result = self._publisher.publish(pid, self._video_path, self._meta)
            except PublishError as exc:
                self.progress.emit(pid, "failed", str(exc), "")
            except Exception as exc:
                self.progress.emit(pid, "failed", f"{type(exc).__name__}: {exc}", "")
            else:
                self.progress.emit(pid, "ok", "", result.url)
