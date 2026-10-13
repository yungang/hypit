"""Event protocol between an agent backend and the UI.

Types and their data:
  step      {id, title, state: running|done|failed}
  message   {role: agent|system, text}
  confirm   {id, prompt, options: [{id, label}]}
  answer    {id, choice, label}      the user's reply to a confirm
  cost      {usd}                    cumulative estimate
  artifact  {kind: video, path}
  done      {status: success|cancelled}
  error     {text}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    type: str
    data: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "data": self.data}, ensure_ascii=False)

    @staticmethod
    def from_json(line: str) -> "Event":
        raw = json.loads(line)
        return Event(raw["type"], raw.get("data", {}))
