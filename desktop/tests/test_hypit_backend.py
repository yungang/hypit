"""Tests for the real (Hypit CLI) backend, using a fake CLI so nothing is spent or run."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypit_desktop.agent.hypit_backend import HypitCliBackend  # noqa: E402
from hypit_desktop.hypit.cli import HypitCli, HypitError  # noqa: E402
from hypit_desktop.hypit.estimate import estimate  # noqa: E402
from hypit_desktop.hypit.failures import classify  # noqa: E402
from hypit_desktop.hypit.project import prepare_project  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "pricing_podcast.json"


class FakeCli:
    use_env_proxy = False

    def __init__(self, statuses, pricing=None, pricing_error=None, outputs=None, check_error=None):
        self.statuses = list(statuses)
        self.pricing_json = pricing if pricing is not None else json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.pricing_by_run = {}
        self.pricing_error = pricing_error
        self.outputs_json = outputs or []
        self.check_error = check_error
        self.calls = []
        self.built_runs = []

    def runtime_up(self, project):
        self.calls.append("runtime_up")

    def select_runtime(self, project, profile="./hypit.runtime.json"):
        self.calls.append("select_runtime")

    def pricing(self, project, run_source):
        self.calls.append("pricing")
        if self.pricing_error:
            raise HypitError(self.pricing_error)
        return self.pricing_by_run.get(run_source, self.pricing_json)

    def check(self, project, run_source):
        self.calls.append("check")
        if self.check_error:
            raise HypitError(self.check_error)

    def outputs(self, project, build_id):
        self.calls.append("outputs")
        return self.outputs_json

    def build(self, project, run_source, title):
        self.calls.append("build")
        self.built_runs.append(run_source)
        return f"bld_{len(self.built_runs)}"

    def status(self, project, build_id):
        self.calls.append("status")
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    def cancel(self, project, build_id):
        self.calls.append("cancel")

    def export(self, project, build_id, output, destination):
        self.calls.append("export")
        Path(destination).write_bytes(b"video")


class Responder:
    def __init__(self, choice="go", sleeps=1000):
        self.choice, self.sleeps = choice, sleeps

    def wait(self, confirm_id):
        return self.choice

    def sleep(self, seconds):
        self.sleeps -= 1
        return self.sleeps > 0


def working(done, total=10):
    return {"work": {"state": "working", "requests": {"total": total, "completed": done}}}


# a finished Build reports no request counts at all (observed with the real CLI)
COMPLETE = {"work": {"state": "done", "outcome": "complete", "requests": {"total": 0, "completed": 0}}}


RUN_FILE = ('<svrun version="1">\n  <author source="./reference.svml"/>\n'
            '  <target output="final.video"/>\n</svrun>\n')


def run_backend(cli, responder, tmp, brief=None):
    project = Path(tmp) / "proj"
    project.mkdir(exist_ok=True)
    (project / "reference.svrun").write_text(RUN_FILE, encoding="utf-8")
    backend = HypitCliBackend(cli, Path(tmp), project_dir=project, poll_seconds=0)
    return list(backend.run({"task_id": 7, "topic": "cat", **(brief or {})}, responder))


class EstimateTests(unittest.TestCase):
    def test_podcast_example_matches_the_real_spend(self):
        est = estimate(json.loads(FIXTURE.read_text(encoding="utf-8")))
        # 24 s Seedance mini 720p + 9 GPT Image 2K + 2 voices + 3 alignments' base fee. Really spent: 342 credits.
        self.assertAlmostEqual(est.credits, 24 * 9.43 + 9 * 11.5 + 2 * 2.6 + 3 * 1.61, places=2)
        self.assertEqual(est.paid_requests, 18)
        self.assertAlmostEqual(est.usd, est.credits / 200)
        self.assertTrue(any("音频时长" in n for n in est.incomplete))

    def test_unknown_duration_is_flagged_not_guessed(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        seedance = next(g for g in data["groups"] if "seedance" in g["capability"])
        for r in seedance["requests"]:
            r["summary"]["fields"]["duration"] = -1
        est = estimate(data)
        self.assertTrue(any("自动决定" in n for n in est.incomplete))
        self.assertAlmostEqual(est.credits, 9 * 11.5 + 2 * 2.6 + 3 * 1.61, places=2)


class FailureTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify("HypiHub HTTP 402; insufficient_credits; you have 0")[0], "credits")
        self.assertEqual(classify("cue:23.visibility is outside Timeline.")[0], "timeline")
        self.assertEqual(classify("rasterize-visual: Network.enable timed out")[0], "browser")
        self.assertEqual(classify("Post Img Risk Not Pass")[0], "review")
        kind, text = classify("x" * 1000)
        self.assertEqual(kind, "other")
        self.assertLess(len(text), 400)


class BackendTests(unittest.TestCase):
    def test_success_reports_progress_cost_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([working(2), working(6), COMPLETE])
            events = run_backend(cli, Responder("go"), tmp)
            types = [e.type for e in events]
            self.assertEqual(types[-1], "done")
            self.assertEqual(events[-1].data["status"], "success")
            confirm = next(e for e in events if e.type == "confirm")
            self.assertIn("积分", confirm.data["prompt"])
            costs = [e.data["usd"] for e in events if e.type == "cost"]
            self.assertEqual(costs, sorted(costs))
            self.assertAlmostEqual(costs[-1], estimate(cli.pricing_json).usd, places=3)
            artifact = next(e for e in events if e.type == "artifact")
            self.assertTrue(Path(artifact.data["path"]).is_file())
            self.assertIn("task-7", artifact.data["path"])
            titles = [e.data["title"] for e in events if e.type == "step" and e.data["id"] == "generate"]
            self.assertIn("生成素材并合成(6/10)", titles)
            self.assertEqual(titles[-1], "生成素材并合成(10/10)")  # no "(0/0)" once the Build is done
            self.assertEqual(cli.calls.count("build"), 1)

    def test_declining_the_price_spends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([COMPLETE])
            events = run_backend(cli, Responder("cancel"), tmp)
            self.assertEqual(events[-1].data["status"], "cancelled")
            self.assertNotIn("build", cli.calls)

    def test_cancel_while_building_cancels_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([working(1)])
            events = run_backend(cli, Responder("go", sleeps=2), tmp)
            self.assertIn("cancel", cli.calls)
            self.assertEqual(events[-1].data["status"], "cancelled")

    def test_out_of_credits_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            failed = {"work": {"state": "done", "outcome": "failed", "requests": {"total": 10, "completed": 3}},
                      "failure": "HypiHub HTTP 402; insufficient_credits; this call costs about 2.6 credits"}
            events = run_backend(FakeCli([failed]), Responder("go"), tmp)
            self.assertEqual(events[-1].type, "error")
            self.assertIn("积分不足", events[-1].data["text"])

    def test_cli_errors_become_error_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = run_backend(FakeCli([COMPLETE], pricing_error="RUNTIME_CREDENTIAL_MISSING"), Responder(), tmp)
            self.assertEqual(events[-1].type, "error")
            self.assertIn("登录", events[-1].data["text"])


TIMELINE_FAILED = {"work": {"state": "done", "outcome": "failed", "requests": {"total": 10, "completed": 8}},
                   "failure": "cue:23.visibility is outside Timeline."}
EARLIER_OUTPUTS = [
    {"name": "girl.image", "kind": "resource", "target": False},
    {"name": "girl-voice.reference", "kind": "resource", "target": False},
    {"name": "opening-take.video", "kind": "resource", "target": False},
    {"name": "opening-semantic.alignment", "kind": "composite", "target": False},
    {"name": "opening-take-prompt", "kind": "composite", "target": False},   # text, no dot
    {"name": "speech.timeline", "kind": "composite", "target": False},       # local, not a paid component
    {"name": "final.video", "kind": "resource", "target": True},
]


class RetryTests(unittest.TestCase):
    def failed_first_run(self, tmp, cli, brief=None):
        cli.statuses = [TIMELINE_FAILED]
        events = run_backend(cli, Responder("go"), tmp, brief)
        self.assertEqual(events[-1].type, "error")
        self.assertIn("不会再付费", events[-1].data["text"])  # the user is told that a retry is free
        return events

    def test_retry_reuses_paid_outputs_and_skips_the_price_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([TIMELINE_FAILED], outputs=EARLIER_OUTPUTS)
            self.failed_first_run(tmp, cli)
            cli.pricing_by_run["retry-1.svrun"] = {"groups": []}  # everything that costs money is reused
            cli.statuses = [COMPLETE]
            events = run_backend(cli, Responder("go"), tmp)
            self.assertEqual(cli.built_runs, ["reference.svrun", "retry-1.svrun"])
            self.assertFalse(any(e.type == "confirm" for e in events))   # nothing left to pay for
            self.assertEqual(events[-1].data["status"], "success")
            self.assertTrue(any("直接复用" in e.data.get("text", "") for e in events if e.type == "message"))
            retry = (Path(tmp) / "proj" / "retry-1.svrun").read_text(encoding="utf-8")
            for name in ("girl.image", "girl-voice.reference", "opening-take.video", "opening-semantic.alignment"):
                self.assertIn(f'<satisfy output="{name}"', retry)
                self.assertIn(f'build="bld_1" output="{name}"', retry)
            for name in ("final.video", "speech.timeline", "opening-take-prompt"):
                self.assertNotIn(f'<satisfy output="{name}"', retry)
            self.assertIn("</svrun>", retry)
            self.assertIn('<target output="final.video"/>', retry)

    def test_retry_still_asks_when_something_paid_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([TIMELINE_FAILED], outputs=EARLIER_OUTPUTS)
            self.failed_first_run(tmp, cli)
            data = json.loads(FIXTURE.read_text(encoding="utf-8"))
            data["groups"] = [g for g in data["groups"] if "seedance" in g["capability"]][:1]
            data["groups"][0]["requests"] = data["groups"][0]["requests"][:1]
            cli.pricing_by_run["retry-1.svrun"] = data
            cli.statuses = [COMPLETE]
            events = run_backend(cli, Responder("go"), tmp)
            prompt = next(e for e in events if e.type == "confirm").data["prompt"]
            self.assertIn("1 个付费请求", prompt)

    def test_a_changed_request_starts_from_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([TIMELINE_FAILED], outputs=EARLIER_OUTPUTS)
            self.failed_first_run(tmp, cli)
            cli.statuses = [COMPLETE]
            run_backend(cli, Responder("go"), tmp, brief={"topic": "dog"})
            self.assertEqual(cli.built_runs, ["reference.svrun", "reference.svrun"])
            self.assertEqual(cli.calls.count("outputs"), 0)

    def test_failed_reuse_falls_back_to_full_price_with_a_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([TIMELINE_FAILED], outputs=EARLIER_OUTPUTS)
            self.failed_first_run(tmp, cli)
            cli.check_error = "unknown output girl.image"
            cli.statuses = [COMPLETE]
            events = run_backend(cli, Responder("go"), tmp)
            self.assertEqual(cli.built_runs[-1], "reference.svrun")
            self.assertTrue(any(e.type == "confirm" for e in events))
            self.assertTrue(any("按全价" in e.data.get("text", "") for e in events if e.type == "message"))

    def test_no_earlier_outputs_means_a_full_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = FakeCli([TIMELINE_FAILED], outputs=[])
            self.failed_first_run(tmp, cli)
            cli.statuses = [COMPLETE]
            events = run_backend(cli, Responder("go"), tmp)
            self.assertEqual(cli.built_runs[-1], "reference.svrun")
            self.assertTrue(any("全部重新生成" in e.data.get("text", "") for e in events if e.type == "message"))


class CliAndProjectTests(unittest.TestCase):
    def test_cli_builds_the_command_and_parses_json(self):
        seen = {}

        def runner(cmd, **kwargs):
            seen["cmd"], seen["kwargs"] = cmd, kwargs
            return SimpleNamespace(returncode=0, stdout='{"build": {"id": "bld_1"}}', stderr="")

        cli = HypitCli(Path("hypit.mjs"), node="node", use_env_proxy=True, runner=runner)
        self.assertEqual(cli.build(Path("proj"), "ref.svrun", "t"), "bld_1")
        self.assertEqual(seen["cmd"][:3], ["node", "hypit.mjs", "build"])
        self.assertIn("--json", seen["cmd"])
        self.assertEqual(seen["kwargs"]["env"]["NODE_USE_ENV_PROXY"], "1")
        self.assertEqual(seen["kwargs"]["cwd"], "proj")

    def test_cli_failure_raises_with_hypit_text(self):
        def runner(cmd, **kwargs):
            return SimpleNamespace(returncode=1, stdout="× Command failed", stderr="CLI_ERROR boom")

        cli = HypitCli(Path("hypit.mjs"), runner=runner)
        with self.assertRaises(HypitError) as ctx:
            cli.status(Path("proj"), "bld_1")
        self.assertIn("boom", str(ctx.exception))

    def test_prepare_project_copies_template_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "template"
            (template / "node_modules").mkdir(parents=True)
            (template / "package.json").write_text('{"name": "t", "hypit": {"project": true}}', encoding="utf-8")
            (template / "reference.svml").write_text("x", encoding="utf-8")
            cli = FakeCli([])
            dest = Path(tmp) / "projects" / "task-1"
            prepare_project(cli, template, dest)
            self.assertTrue((dest / "reference.svml").is_file())
            self.assertFalse((dest / "node_modules" / "ignored").exists())
            self.assertEqual(cli.calls, ["select_runtime"])


if __name__ == "__main__":
    unittest.main()
