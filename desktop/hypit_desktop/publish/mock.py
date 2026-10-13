"""Stand-in publisher for UI development: nothing leaves the machine."""
from __future__ import annotations

import time

from .base import PublishError, PublishMeta, PublishResult


class MockPublisher:
    def __init__(self, delay: float = 0.8):
        self.delay = delay

    def publish(self, platform_id: str, video_path: str, meta: PublishMeta) -> PublishResult:
        time.sleep(self.delay)
        if platform_id == "pdd":  # exercises the failure path in the UI
            raise PublishError("演示:该平台没有可用的发布接口")
        return PublishResult(url=f"https://example.invalid/{platform_id}/demo")
