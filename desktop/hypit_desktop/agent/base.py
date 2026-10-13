"""The only surface the UI depends on. A real backend (Claude Agent SDK driving
the Hypit CLI) implements the same AgentBackend protocol as the replay one."""
from __future__ import annotations

from typing import Iterator, Optional, Protocol

from ..events import Event


class Responder(Protocol):
    def wait(self, confirm_id: str) -> Optional[str]:
        """Block until the user answers a confirm; None if the task was cancelled."""

    def sleep(self, seconds: float) -> bool:
        """Cancellable sleep; False if the task was cancelled meanwhile."""


class AgentBackend(Protocol):
    def run(self, brief: dict, responder: Responder) -> Iterator[Event]:
        ...
