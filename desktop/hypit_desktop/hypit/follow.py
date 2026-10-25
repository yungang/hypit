"""Watch one Hypit Build until it ends, turning its progress into events."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from ..events import Event
from .cli import HypitCli, HypitError
from .estimate import Estimate

MAX_WAIT_SECONDS = 3 * 3600


@dataclass
class BuildOutcome:
    status: str          # "complete" | "failed" | "cancelled" | "timeout"
    build_id: str
    failure: str = ""
    total: int = 0


def follow_build(cli: HypitCli, project: Path, build_id: str, est: Estimate, base_usd: float, responder,
                 poll_seconds: float, step_id: str = "generate",
                 label: str = "生成素材并合成") -> Generator[Event, None, BuildOutcome]:
    """Yield progress events; the generator's return value is the BuildOutcome.

    `base_usd` is what earlier attempts of the same task are estimated to have cost, so the cost shown to the
    user keeps climbing across automatic retries instead of restarting at zero."""
    waited, last_done, known_total = 0.0, -1, 0
    yield Event("step", {"id": step_id, "title": label, "state": "running"})
    while True:
        build = cli.status(project, build_id)
        work = build.get("work", {})
        requests = work.get("requests") or {}
        done_count, total = requests.get("completed", 0), requests.get("total", 0)
        if total and done_count != last_done:  # a finished Build reports 0/0, so remember the last real figure
            last_done, known_total = done_count, total
            yield Event("step", {"id": step_id, "title": f"{label}({done_count}/{total})", "state": "running"})
            yield Event("cost", {"usd": round(base_usd + est.usd * done_count / total, 4)})
        if work.get("state") == "done":
            break
        if waited >= MAX_WAIT_SECONDS:
            _cancel_quietly(cli, project, build_id)
            return BuildOutcome("timeout", build_id, "等待超过 3 小时,已取消这次生成。", known_total)
        if not responder.sleep(poll_seconds):
            _cancel_quietly(cli, project, build_id)
            return BuildOutcome("cancelled", build_id, "", known_total)
        waited += poll_seconds

    if work.get("outcome") == "complete":
        yield Event("step", {"id": step_id, "title": f"{label}({known_total}/{known_total})", "state": "done"})
        yield Event("cost", {"usd": round(base_usd + est.usd, 4)})
        return BuildOutcome("complete", build_id, "", known_total)
    yield Event("step", {"id": step_id, "title": label, "state": "failed"})
    return BuildOutcome("failed", build_id, build.get("failure") or "任务失败,没有给出原因", known_total)


def _cancel_quietly(cli: HypitCli, project: Path, build_id: str) -> None:
    try:
        cli.cancel(project, build_id)
    except HypitError:
        pass  # already finished or not cancellable; the caller reports its own outcome
