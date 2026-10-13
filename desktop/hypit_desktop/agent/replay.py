"""Plays back a recorded event stream (JSONL) so the UI can be built without
spending model credits. Each line: {"delay": seconds, "type": ..., "data": {...}}.
"{url}", "{topic}" etc. in strings are filled from the task brief."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..events import Event
from .base import Responder

DEFAULT_SCRIPT = Path(__file__).parent / "fixtures" / "demo_clone.jsonl"

# scenario id -> (label shown in settings, script)
SCENARIOS = {
    "normal": ("演示:正常完成", DEFAULT_SCRIPT),
    "fail": ("演示:中途失败", DEFAULT_SCRIPT.with_name("demo_fail.jsonl")),
}


def _fill(value, brief: dict):
    if isinstance(value, str):
        for key, item in brief.items():
            value = value.replace("{" + key + "}", str(item))
        return value
    if isinstance(value, list):
        return [_fill(v, brief) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, brief) for k, v in value.items()}
    return value


class ReplayAgent:
    def __init__(self, script: Path = DEFAULT_SCRIPT, speed: float = 1.0):
        self.script = Path(script)
        self.speed = speed

    def run(self, brief: dict, responder: Responder) -> Iterator[Event]:
        for line in self.script.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            if not responder.sleep(raw.get("delay", 0.5) / self.speed):
                yield Event("done", {"status": "cancelled"})
                return
            event = Event(raw["type"], _fill(raw.get("data", {}), brief))
            yield event
            if event.type != "confirm":
                continue
            choice = responder.wait(event.data["id"])
            if choice is None:
                yield Event("done", {"status": "cancelled"})
                return
            labels = {o["id"]: o["label"] for o in event.data["options"]}
            yield Event("answer", {"id": event.data["id"], "choice": choice,
                                   "label": labels.get(choice, choice)})
            if choice == "cancel":
                yield Event("message", {"role": "agent", "text": "好的,已取消本次任务。"})
                yield Event("done", {"status": "cancelled"})
                return


def replay_backend_factory(settings) -> ReplayAgent:
    """Build the replay backend from user settings (anything with .get())."""
    _, script = SCENARIOS.get(settings.get("scenario"), SCENARIOS["normal"])
    return ReplayAgent(script, speed=float(settings.get("replay_speed")))
