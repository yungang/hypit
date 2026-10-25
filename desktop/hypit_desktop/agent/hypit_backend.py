"""AgentBackend that drives the real Hypit CLI for one fixed project template.

No model decides anything yet: the brief's parameters are not applied to the video. This backend owns the
plumbing: project, price check, paid Build, progress, export, failures, and retries that re-use what
was already bought (a Hypit Build never re-uses anything unless a Run says so)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator, Optional

from ..events import Event
from ..hypit.cli import HypitCli, HypitError
from ..hypit.estimate import Estimate, estimate
from ..hypit.failures import classify
from ..hypit.project import prepare_project
from ..hypit.reuse import (brief_fingerprint, load_state, paid_components, reusable_outputs,
                           save_state, write_retry_run)
from .base import Responder

TEMPLATE_DEFAULT = Path(__file__).resolve().parents[2] / "templates" / "podcast"
FINAL_OUTPUT = "final.video"
MAX_WAIT_SECONDS = 3 * 3600


def _step(step_id: str, title: str, state: str) -> Event:
    return Event("step", {"id": step_id, "title": title, "state": state})


def _message(text: str) -> Event:
    return Event("message", {"role": "agent", "text": text})


def describe_estimate(est: Estimate) -> str:
    text = f"预计花费约 {est.credits:.0f} 积分(约 ${est.usd:.2f},{est.paid_requests} 个付费请求)"
    if est.incomplete:
        text += "。这是估算:" + ";".join(est.incomplete)
    return text


class HypitCliBackend:
    def __init__(self, cli: HypitCli, data_dir: Path, template: Path = TEMPLATE_DEFAULT,
                 project_dir: Optional[Path] = None, run_source: str = "reference.svrun",
                 poll_seconds: float = 5.0):
        self.cli = cli
        self.data_dir = Path(data_dir).resolve()
        self.template = Path(template)
        self.project_dir = Path(project_dir) if project_dir else None  # dev: use an existing project as is
        self.run_source = run_source
        self.poll_seconds = poll_seconds

    # --- helpers -----------------------------------------------------------------------------
    def _project_for(self, task_id: int) -> Path:
        if self.project_dir is not None:
            return self.project_dir
        destination = self.data_dir / "projects" / f"task-{task_id}"
        return prepare_project(self.cli, self.template, destination)

    def _export_path(self, task_id: int) -> Path:
        folder = self.data_dir / "outputs" / f"task-{task_id}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"final-{time.strftime('%Y%m%d-%H%M%S')}.mp4"

    def _plan_retry(self, project: Path, previous: str, full_pricing: dict, attempt: int):
        """Build a Run that re-uses the paid Outputs of `previous`.

        Returns ((run file, estimate, reused count), None) or (None, why not)."""
        try:
            names = reusable_outputs(self.cli.outputs(project, previous), paid_components(full_pricing))
            if not names:
                return None, "上次没有留下可复用的素材,这次要全部重新生成。"
            run_file = f"retry-{attempt}.svrun"
            write_retry_run(project, self.run_source, previous, names, run_file)
            self.cli.check(project, run_file)
            return (run_file, estimate(self.cli.pricing(project, run_file)), len(names)), None
        except (HypitError, OSError, ValueError) as exc:
            reason = " ".join(str(exc).split())[:120]
            return None, f"没能复用上次的素材({reason}),这次会按全价重新生成。"

    # --- the run ---------------------------------------------------------------------------------
    def run(self, brief: dict, responder: Responder) -> Iterator[Event]:
        task_id = int(brief.get("task_id", 0))
        title = brief.get("topic") or f"task-{task_id}"
        try:
            yield from self._run(brief, task_id, title, responder)
        except HypitError as exc:
            kind, text = classify(str(exc))
            yield Event("error", {"text": text})

    def _run(self, brief: dict, task_id: int, title: str, responder: Responder) -> Iterator[Event]:
        yield _message("当前使用固定的示例模板(播客对话),界面里的主题、产品、图片等参数暂时还不会改变视频内容。")

        yield _step("prepare", "准备项目和运行环境", "running")
        project = self._project_for(task_id)
        self.cli.runtime_up(project)
        yield _step("prepare", "准备项目和运行环境", "done")

        fingerprint = brief_fingerprint(brief)
        state = load_state(project)
        if state.get("fingerprint") != fingerprint:  # a different request: nothing from before applies
            state = {"fingerprint": fingerprint, "builds": []}

        yield _step("price", "核对计划与价格", "running")
        full_pricing = self.cli.pricing(project, self.run_source)
        run_source, est, reused = self.run_source, estimate(full_pricing), 0
        if state["builds"]:
            plan, why_not = self._plan_retry(project, state["builds"][-1]["id"], full_pricing, len(state["builds"]))
            if plan is not None:
                run_source, est, reused = plan
                yield _message(f"找到上次生成的 {reused} 个素材,这次直接复用,不再重复付费。")
            else:
                yield _message(why_not)
        yield _step("price", "核对计划与价格", "done")
        yield Event("cost", {"usd": 0.0})

        if est.paid_requests == 0:
            yield _message("这次不需要任何付费请求,直接在本地合成。")
        else:
            yield Event("confirm", {
                "id": "budget",
                "prompt": describe_estimate(est) + "。是否开始生成?",
                "options": [{"id": "go", "label": "确认生成"}, {"id": "cancel", "label": "取消"}],
            })
            choice = responder.wait("budget")
            if choice is None:
                yield Event("done", {"status": "cancelled"})
                return
            labels = {"go": "确认生成", "cancel": "取消"}
            yield Event("answer", {"id": "budget", "choice": choice, "label": labels.get(choice, choice)})
            if choice != "go":
                yield _message("好的,已取消,没有产生任何费用。")
                yield Event("done", {"status": "cancelled"})
                return

        yield _step("build", "提交生成任务", "running")
        build_id = self.cli.build(project, run_source, f"{title} (task {task_id})")
        state["builds"].append({"id": build_id, "run": run_source})
        save_state(project, state)  # remembered so that a retry can re-use this Build's Outputs
        yield _step("build", "提交生成任务", "done")
        yield from self._follow(project, build_id, est, task_id, responder)

    def _follow(self, project: Path, build_id: str, est: Estimate, task_id: int,
                responder: Responder) -> Iterator[Event]:
        waited = 0.0
        last_done = -1
        known_total = 0  # a finished Build reports 0/0 requests, so remember the last real figure
        yield _step("generate", "生成素材并合成", "running")
        while True:
            build = self.cli.status(project, build_id)
            work = build.get("work", {})
            requests = work.get("requests") or {}
            done_count, total = requests.get("completed", 0), requests.get("total", 0)
            if total and done_count != last_done:
                last_done, known_total = done_count, total
                yield _step("generate", f"生成素材并合成({done_count}/{total})", "running")
                # spend is only known at the end; show the estimate in proportion to progress
                yield Event("cost", {"usd": round(est.usd * done_count / total, 4)})
            if work.get("state") == "done":
                break
            if waited >= MAX_WAIT_SECONDS:
                self._cancel_quietly(project, build_id)
                yield Event("error", {"text": "等待超过 3 小时,已取消这次生成。"})
                return
            if not responder.sleep(self.poll_seconds):
                self._cancel_quietly(project, build_id)
                yield _step("generate", "生成素材并合成", "failed")
                yield _message("已请求取消。已经提交给服务商的部分可能仍会计费;已生成的素材下次重新运行时会复用。")
                yield Event("done", {"status": "cancelled"})
                return
            waited += self.poll_seconds

        if work.get("outcome") == "complete":
            yield _step("generate", f"生成素材并合成({known_total}/{known_total})", "done")
            yield Event("cost", {"usd": round(est.usd, 4)})
            yield _step("export", "导出成片", "running")
            target = self._export_path(task_id)
            self.cli.export(project, build_id, FINAL_OUTPUT, target)
            yield _step("export", "导出成片", "done")
            yield Event("artifact", {"kind": "video", "path": str(target)})
            yield _message(f"完成了!成片已保存到 {target}")
            yield Event("done", {"status": "success"})
            return

        yield _step("generate", "生成素材并合成", "failed")
        kind, text = classify(build.get("failure") or "任务失败,没有给出原因")
        yield Event("error", {"text": text + "(已生成的素材会保留,重新运行时自动复用,不会再付费。)"
                              if kind != "credits" else text})

    def _cancel_quietly(self, project: Path, build_id: str) -> None:
        try:
            self.cli.cancel(project, build_id)
        except HypitError:
            pass  # already finished or not cancellable; the caller reports its own outcome
