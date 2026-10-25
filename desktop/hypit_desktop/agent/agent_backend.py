"""AgentBackend: a director agent writes the production, the app prices it, asks, builds, retries and exports.

Money rule: the agent only authors and plans (its `hypit` command is guarded). Every `hypit build` is issued
here, after the user has seen the estimate, and automatic retries stay inside a spending margin."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from ..briefs import normalize
from ..events import Event
from ..hypit.cli import HypitCli, HypitError
from ..hypit.estimate import Estimate, estimate
from ..hypit.failures import classify, is_script_problem, is_transient
from ..hypit.follow import BuildOutcome, follow_build
from ..hypit.reuse import brief_fingerprint, load_state, plan_retry, save_state
from .base import Responder
from .director import Director, PhaseResult
from .models import plan_models
from .prompts import (RUN_PATH, SOURCE_PATH, build_feedback_prompt, build_repair_prompt, build_task_prompt)
from .workspace import Workspace, find_skill_dir, prepare_workspace

FINAL_OUTPUT = "final.video"
KEPT_NOTE = "(已生成的素材会保留,重新运行时自动复用,不会再付费。)"


@dataclass
class AgentConfig:
    launcher: str
    node: str = "node"
    use_env_proxy: bool = True
    llm_base_url: str = "https://api.deepseek.com/anthropic"
    llm_model: str = "deepseek-flash"
    llm_key_env: str = "DEEPSEEK_API_KEY"
    skill_dir: str = ""
    max_turns: int = 150
    max_auto_retries: int = 3        # re-submissions after a transient error
    max_script_repairs: int = 2      # director edits after a script-level failure
    budget_margin: float = 1.5       # ask again once the estimated total passes this multiple of the approval
    retry_delay_seconds: float = 20.0
    poll_seconds: float = 5.0


def _step(step_id: str, title: str, state: str) -> Event:
    return Event("step", {"id": step_id, "title": title, "state": state})


def _message(text: str) -> Event:
    return Event("message", {"role": "agent", "text": text})


def describe_estimate(est: Estimate) -> str:
    text = f"预计花费约 {est.credits:.0f} 积分(约 ${est.usd:.2f},{est.paid_requests} 个付费请求)"
    if est.incomplete:
        text += "。这是估算:" + ";".join(est.incomplete)
    return text


class HypitAgentBackend:
    def __init__(self, cli: HypitCli, data_dir: Path, config: AgentConfig,
                 director_factory: Optional[Callable[[Path, str], Director]] = None,
                 workspace_factory: Optional[Callable[..., Workspace]] = None):
        self.cli, self.data_dir, self.config = cli, Path(data_dir).resolve(), config
        self._director_factory = director_factory or self._default_director
        self._workspace_factory = workspace_factory or prepare_workspace

    def _default_director(self, project: Path, api_key: str) -> Director:
        c = self.config
        return Director(project, api_key, c.llm_base_url, c.llm_model, c.launcher, c.node, c.max_turns, c.use_env_proxy)

    # --- entry point --------------------------------------------------------------------------------
    def run(self, brief: dict, responder: Responder) -> Iterator[Event]:
        try:
            yield from self._run({**normalize(brief), "task_id": brief.get("task_id", 0)}, responder)
        except HypitError as exc:
            kind, text = classify(str(exc))
            yield Event("error", {"text": text if kind != "other" else str(exc)[:400]})

    def _cancelled(self, responder) -> bool:
        return not responder.sleep(0)

    def _run(self, brief: dict, responder: Responder) -> Iterator[Event]:
        c = self.config
        task_id = int(brief["task_id"])
        project_id = int(brief.get("project_from") or task_id)

        models = plan_models(brief)
        if models.problems:
            yield Event("error", {"text": " ".join(models.problems)})
            return
        api_key = os.environ.get(c.llm_key_env, "")
        if not api_key:
            yield Event("error", {"text": f"没有找到 AI 导演的密钥。请在系统环境变量 {c.llm_key_env} 里设置它,然后重新运行。"})
            return

        yield _step("prepare", "准备项目和素材", "running")
        workspace = self._workspace_factory(self.cli, self.data_dir, project_id, brief, models,
                                            find_skill_dir(c.skill_dir), c.node)
        project = workspace.path
        self.cli.runtime_up(project)
        yield _step("prepare", "准备项目和素材", "done")

        fingerprint = brief_fingerprint({k: v for k, v in brief.items() if k != "project_from"})
        state = load_state(project)
        feedback = brief.get("feedback", "")
        has_source = (project / SOURCE_PATH).is_file() and (project / RUN_PATH).is_file()
        reuse_authoring = (not feedback and has_source and state.get("authored")
                           and state.get("fingerprint") == fingerprint)
        if not reuse_authoring:
            state = {"fingerprint": fingerprint, "builds": state.get("builds", []) if feedback else [], "authored": False}
            director = self._director_factory(project, api_key)
            yield _step("director", "AI 导演工作中", "running")
            if feedback:
                last = next((b["id"] for b in reversed(state["builds"]) if b.get("ok")), "")
                prompt = build_feedback_prompt(feedback, brief.get("feedback_at"), last, c.max_turns)
            else:
                prompt = build_task_prompt(brief, models, workspace.images, c.max_turns)
            result = PhaseResult()
            yield from director.run_phase(prompt, bool(feedback), lambda: self._cancelled(responder), result)
            if self._cancelled(responder):
                yield Event("done", {"status": "cancelled"})
                return
            problem = yield from self._verify(director, project, result, responder)
            if problem:
                yield Event("error", {"text": problem})
                return
            state["authored"] = True
            save_state(project, state)
            yield _message("脚本写好了:" + (result.summary or "(导演没有给出总结)"))
        else:
            yield _message("沿用上次写好的脚本,不用重新创作。")

        yield from self._price_confirm_build(brief, project, state, responder, models, api_key, task_id)

    # --- after authoring: the files must exist and pass `hypit check` -------------------------------------
    def _verify(self, director: Director, project: Path, result: PhaseResult, responder) -> Iterator[Event]:
        """Return a problem description (as the generator's return value) or '' when the production is valid."""
        for attempt in range(3):
            if not result.ok and not (project / RUN_PATH).is_file():
                return result.error or "AI 导演没有完成创作。"
            error = ""
            for path in (SOURCE_PATH, RUN_PATH):
                if not (project / path).is_file():
                    error = f"导演没有写出 {path}。"
                    break
                try:
                    self.cli.check(project, path)
                except HypitError as exc:
                    error = f"{path} 没有通过 hypit check:{str(exc)[:600]}"
                    break
            if not error:
                return ""
            if attempt == 2:
                return error
            yield _message(f"脚本检查没通过,让导演修正(第 {attempt + 1} 次)。")
            result = PhaseResult()
            yield from director.run_phase(build_repair_prompt("check", error), True,
                                          lambda: self._cancelled(responder), result)
        return "脚本多次检查都没有通过。"

    # --- pricing, confirmation, building with automatic retries ------------------------------------------
    def _price_confirm_build(self, brief: dict, project: Path, state: dict, responder, models, api_key: str,
                             task_id: int) -> Iterator[Event]:
        c = self.config
        yield _step("price", "核对计划与价格", "running")
        full_pricing = self.cli.pricing(project, RUN_PATH)
        run_source, est = RUN_PATH, estimate(full_pricing)
        previous = state["builds"][-1]["id"] if state["builds"] else ""
        if previous and not brief.get("feedback"):
            plan, why = plan_retry(self.cli, project, RUN_PATH, previous, full_pricing, len(state["builds"]))
            if plan is not None:
                run_source, est, reused = plan
                yield _message(f"找到上次生成的 {reused} 个素材,这次直接复用,不再重复付费。")
            else:
                yield _message(f"没能复用上次的素材({why}),这次按全价生成。")
        yield _step("price", "核对计划与价格", "done")
        yield Event("cost", {"usd": 0.0})

        approved = est.credits
        if est.paid_requests:
            ok = yield from self._confirm(est, "。重试和失败可能带来少量额外损耗,通常不超过预估的 1.3 倍。是否开始生成?", responder)
            if not ok:
                yield Event("done", {"status": "cancelled"})
                return
        else:
            yield _message("这次不需要任何付费请求,直接在本地合成。")

        spent_credits, attempts, repairs = 0.0, 0, 0
        while True:
            yield _step("build", "提交生成任务", "running")
            build_id = self.cli.build(project, run_source, f"{brief.get('topic', '')} (task {task_id})")
            state["builds"].append({"id": build_id, "run": run_source, "ok": False})
            save_state(project, state)
            yield _step("build", "提交生成任务", "done")
            spent_credits += est.credits
            outcome: BuildOutcome = yield from follow_build(
                self.cli, project, build_id, est, (spent_credits - est.credits) / est.credits_per_usd,
                responder, c.poll_seconds)

            if outcome.status == "cancelled":
                yield _message("已请求取消。已经提交给服务商的部分可能仍会计费;已生成的素材下次重新运行时会复用。")
                yield Event("done", {"status": "cancelled"})
                return
            if outcome.status == "complete":
                state["builds"][-1]["ok"] = True
                save_state(project, state)
                yield from self._export(project, build_id, task_id)
                return

            kind, text = classify(outcome.failure)
            # ---- decide whether the app can fix this by itself ----
            if is_transient(kind) and attempts < c.max_auto_retries:
                attempts += 1
                delay = c.retry_delay_seconds * attempts
                yield _message(f"遇到临时故障({text})。{delay:.0f} 秒后自动复用已生成的素材重试"
                               f"(第 {attempts}/{c.max_auto_retries} 次)。")
                if not responder.sleep(delay):
                    yield Event("done", {"status": "cancelled"})
                    return
            elif is_script_problem(kind) and repairs < c.max_script_repairs:
                repairs += 1
                yield _message(f"合成时发现脚本问题:{text} 让 AI 导演修正(第 {repairs}/{c.max_script_repairs} 次)。")
                director = self._director_factory(project, api_key)
                result = PhaseResult()
                yield _step("director", "AI 导演修正脚本", "running")
                yield from director.run_phase(build_repair_prompt(kind, outcome.failure[:1500]), True,
                                              lambda: self._cancelled(responder), result)
                problem = yield from self._verify(director, project, result, responder)
                if problem:
                    yield Event("error", {"text": problem + KEPT_NOTE})
                    return
            else:
                extra = "" if kind == "credits" else KEPT_NOTE
                yield Event("error", {"text": text + extra})
                return

            # ---- re-submit, re-using everything already bought ----
            plan, why = plan_retry(self.cli, project, RUN_PATH, build_id, self.cli.pricing(project, RUN_PATH),
                                   len(state["builds"]))
            if plan is None:
                yield _message(f"没能复用已生成的素材({why}),重试会按全价生成。")
                run_source, est = RUN_PATH, estimate(self.cli.pricing(project, RUN_PATH))
            else:
                run_source, est, _ = plan
            if est.paid_requests and (spent_credits + est.credits) > approved * c.budget_margin:
                ok = yield from self._confirm(
                    est, f"。累计预计将达 {spent_credits + est.credits:.0f} 积分,超过你确认的 {approved:.0f} 积分的 "
                         f"{c.budget_margin:g} 倍。是否继续?", responder)
                if not ok:
                    yield _message("好的,已停止。已经生成的素材已保存,以后重新运行会复用。")
                    yield Event("done", {"status": "cancelled"})
                    return

    def _confirm(self, est: Estimate, tail: str, responder) -> Iterator[Event]:
        """Show a confirm card; the generator's return value is True when the user agreed."""
        confirm_id = f"budget-{int(time.time() * 1000)}"
        yield Event("confirm", {"id": confirm_id, "prompt": describe_estimate(est) + tail,
                                "options": [{"id": "go", "label": "确认生成"}, {"id": "cancel", "label": "取消"}]})
        choice = responder.wait(confirm_id)
        if choice is None:
            return False
        yield Event("answer", {"id": confirm_id, "choice": choice,
                               "label": {"go": "确认生成", "cancel": "取消"}.get(choice, choice)})
        return choice == "go"

    def _export(self, project: Path, build_id: str, task_id: int) -> Iterator[Event]:
        yield _step("export", "导出成片", "running")
        folder = self.data_dir / "outputs" / f"task-{task_id}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"final-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
        self.cli.export(project, build_id, FINAL_OUTPUT, target)
        yield _step("export", "导出成片", "done")
        yield Event("artifact", {"kind": "video", "path": str(target)})
        yield _message(f"完成了!成片已保存到 {target}")
        yield Event("done", {"status": "success"})
