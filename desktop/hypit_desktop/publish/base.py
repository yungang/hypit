"""Publishing surface. A real publisher per platform (official open API where one
exists) implements the same protocol; the UI depends only on this."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class PublishError(Exception):
    """A platform refused or could not take the video; the message is shown to the user."""


@dataclass(frozen=True)
class PublishMeta:
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PublishResult:
    url: str = ""


class Publisher(Protocol):
    def publish(self, platform_id: str, video_path: str, meta: PublishMeta) -> PublishResult:
        """Blocking; raise PublishError on failure."""
