"""Headless checks: python -m unittest discover -s tests (from the desktop/ directory)."""
import os
import sys
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from hypit_desktop.agent.replay import SCENARIOS, ReplayAgent, replay_backend_factory  # noqa: E402
from hypit_desktop.briefs import DEFAULTS, summary_of, title_of  # noqa: E402
from hypit_desktop import video_title  # noqa: E402
from hypit_desktop.db import TaskStore  # noqa: E402
from hypit_desktop.events import Event  # noqa: E402
from hypit_desktop.featured_seed import seed_featured  # noqa: E402
from hypit_desktop.publish.mock import MockPublisher  # noqa: E402
from hypit_desktop.settings import Settings  # noqa: E402
from hypit_desktop.ui.main_window import MainWindow  # noqa: E402
from hypit_desktop.ui.publish_dialog import PublishDialog  # noqa: E402
from hypit_desktop.ui.stats_page import day_start  # noqa: E402

BRIEF = {**DEFAULTS, "url": "https://example.com/v", "topic": "猫"}


class FakeResponder:
    def __init__(self, choice):
        self.choice = choice

    def wait(self, confirm_id):
        return self.choice

    def sleep(self, seconds):
        return True


def app():
    return QApplication.instance() or QApplication([])


def make_window(tmp, speed=1000, concurrent=2):
    store = TaskStore(Path(tmp) / "t.db")
    settings = Settings(Path(tmp) / "s.json")
    settings.set("replay_speed", speed)
    settings.set("max_concurrent", concurrent)
    win = MainWindow(store, replay_backend_factory, MockPublisher(0), settings, Path(tmp), title_fetcher=None)
    return store, settings, win


def pump(condition, timeout_ms=15000, auto_confirm=None):
    """Run the Qt event loop until condition() is true (optionally clicking confirm cards)."""
    loop, timer = QEventLoop(), QTimer()
    timer.setInterval(20)

    def tick():
        if auto_confirm:
            for page in auto_confirm._pages.values():
                card = page._cards.get("budget")
                if card and card._buttons["go"].isEnabled():
                    card._buttons["go"].click()
        if condition():
            loop.quit()

    timer.timeout.connect(tick)
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return condition()


class ReplayTests(unittest.TestCase):
    def test_full_run_fills_brief_and_finishes(self):
        events = list(ReplayAgent(speed=1000).run(BRIEF, FakeResponder("go")))
        self.assertEqual(events[-1].data["status"], "success")
        self.assertIn("猫", next(e for e in events if e.type == "confirm").data["prompt"])

    def test_cancel_choice_stops_early(self):
        events = list(ReplayAgent(speed=1000).run(BRIEF, FakeResponder("cancel")))
        self.assertEqual(events[-1].data["status"], "cancelled")
        self.assertFalse(any(e.type == "artifact" for e in events))

    def test_fail_scenario_ends_with_error(self):
        events = list(ReplayAgent(SCENARIOS["fail"][1], speed=1000).run(BRIEF, FakeResponder("go")))
        self.assertEqual(events[-1].type, "error")


class BriefTests(unittest.TestCase):
    def test_title_and_summary(self):
        self.assertEqual(title_of({**BRIEF, "topic": "t1"}), "t1")
        self.assertIn("沿用原视频画面", summary_of(BRIEF))
        self.assertIn("替换:角色、背景", summary_of({**BRIEF, "role_image": "a.png", "background_image": "b.png"}))


class VideoTitleTests(unittest.TestCase):
    def test_platform_and_id(self):
        url = "https://www.douyin.com/video/7684610633048342905"
        self.assertEqual(video_title.platform_of(url), "抖音")
        self.assertEqual(video_title.video_id_of(url), "7684610633048342905")
        self.assertEqual(video_title.fallback_title(url), "抖音_7684610633048342905")
        yt = "https://www.youtube.com/watch?v=abc123XYZ_-"
        self.assertEqual(video_title.fallback_title(yt), "YouTube_abc123XYZ_-")
        self.assertEqual(video_title.fallback_title("https://youtu.be/dQw4w9WgXcQ"), "YouTube_dQw4w9WgXcQ")
        self.assertEqual(video_title.fallback_title("https://example.com/a/b"), "example.com_b")

    def test_generic_titles_are_rejected(self):
        url = "https://www.douyin.com/video/1"
        self.assertEqual(video_title.clean_title("  抖音 ", url), "")
        self.assertEqual(video_title.clean_title("请完成验证", url), "")
        self.assertEqual(video_title.clean_title("猫猫 &amp; 狗狗 - 抖音", url), "猫猫 & 狗狗")
        self.assertEqual(video_title.fetch_title("ftp://x"), None)


class ReplaceTableTests(unittest.TestCase):
    def make_png(self, tmp, name="a.png"):
        from PySide6.QtGui import QPixmap
        path = str(Path(tmp) / name)
        pixmap = QPixmap(40, 30)
        pixmap.fill()
        self.assertTrue(pixmap.save(path))
        return path

    def test_rows_images_and_default_topic(self):
        app()
        from hypit_desktop.ui.replace_table import ReplaceTable
        with tempfile.TemporaryDirectory() as tmp:
            table = ReplaceTable()
            table.reset("auto name")
            self.assertEqual(table.rows(), [{"topic": "auto name", "role_image": "", "product_image": "",
                                             "background_image": ""}])
            png = self.make_png(tmp)
            table.set_image(0, 1, png)
            self.assertFalse(table.item(0, 1).icon().isNull())  # a thumbnail is shown
            self.assertEqual(table.rows()[0]["role_image"], png)
            table.set_default_topic("new name")  # untouched themes follow the source
            self.assertEqual(table.rows()[0]["topic"], "new name")
            table.item(0, 0).setText("mine")  # a user-written theme is left alone
            table.set_default_topic("other")
            self.assertEqual(table.rows()[0]["topic"], "mine")
            table.add_row("second")
            self.assertEqual(table.rowCount(), 2)
            table.set_image(0, 1, "")
            self.assertTrue(table.item(0, 1).icon().isNull())


class StoreTests(unittest.TestCase):
    def test_rename_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "t.db")
            tid = store.create_task("a", BRIEF)
            store.add_event(tid, Event("done", {}))
            store.rename_task(tid, "b")
            self.assertEqual(store.task(tid)["title"], "b")
            store.delete_task(tid)
            self.assertEqual(store.tasks(), [])
            store.close()

    def test_queue_order_and_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "t.db")
            a, b, c = (store.create_task(n, BRIEF) for n in "abc")
            store.move(c, "pending", 0)
            self.assertEqual([r["title"] for r in store.pending_tasks()], ["c", "a", "b"])
            store.move(a, "waiting")
            store.move(b, "waiting", 0)
            self.assertEqual([r["title"] for r in store.tasks_with_status("waiting")], ["b", "a"])
            self.assertEqual([r["title"] for r in store.pending_tasks()], ["c"])
            store.set_status(a, "running")
            done = store.create_task("d", BRIEF, status="waiting")
            store.set_status(done, "success")
            order = [r["title"] for r in store.execution_tasks()]
            self.assertEqual(order, ["a", "b", "d"])  # running, waiting, finished last
            store.close()

    def test_startup_resets_running_and_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "t.db")
            r = store.create_task("r", BRIEF, status="running")
            w = store.create_task("w", BRIEF, status="waiting")
            store.close()
            store = TaskStore(Path(tmp) / "t.db")
            self.assertEqual(store.task(r)["status"], "interrupted")
            self.assertEqual(store.task(w)["status"], "pending")
            store.close()

    def test_artifacts_templates_featured(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "t.db")
            aid = store.add_artifact(None, "x.mp4", "t")
            store.update_artifact(aid, rating=4, tags="a,b", status="kept")
            row = store.artifact(aid)
            self.assertEqual((row["rating"], row["tags"], row["status"]), (4, "a,b", "kept"))
            store.save_template("n", {"model": "Wan 3.0"})
            self.assertEqual(store.templates(), {"n": {"model": "Wan 3.0"}})
            settings = Settings(Path(tmp) / "s.json")
            seed_featured(store, settings)
            seed_featured(store, settings)  # idempotent
            self.assertEqual(len(store.featured()), 7)
            store.close()


class UiTests(unittest.TestCase):
    def test_task_runs_to_completion_publishes_and_exports(self):
        app()
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp)
            win._submit([dict(BRIEF)], "waiting", None)
            task_id = store.tasks()[0]["id"]
            page = win._pages[task_id]
            self.assertTrue(pump(lambda: store.task(task_id)["status"] == "success", auto_confirm=win))
            row = store.task(task_id)
            self.assertAlmostEqual(row["total_cost"], 1.15)
            runs = store.runs(task_id)
            self.assertEqual((len(runs), runs[0]["status"], runs[0]["model"]), (1, "success", "Seedance 2.5"))
            self.assertEqual(len(store.artifacts()), 1)  # the finished video reached the works library
            self.assertFalse(page._publish.isHidden())

            dlg = PublishDialog(store, MockPublisher(0), task_id, page.video_path, "t")
            dlg.confirm.setChecked(True)
            dlg._checks["douyin"].setChecked(True)
            self.assertFalse(dlg.publish_btn.isEnabled())  # selected platform not authorized yet
            dlg.confirm.setChecked(False)
            for pid in ("douyin", "pdd"):
                dlg._toggle_auth(pid)
                dlg._checks[pid].setChecked(True)
            self.assertFalse(dlg.publish_btn.isEnabled())  # needs the confirmation tick
            dlg.confirm.setChecked(True)
            self.assertTrue(dlg.publish_btn.isEnabled())
            dlg._publish()
            dlg._worker.wait(5000)
            QCoreApplication.processEvents()
            states = {r["platform"]: r["state"] for r in store.publishes(task_id)}
            self.assertEqual(states, {"douyin": "ok", "pdd": "failed"})
            out = Path(tmp) / "out"
            out.mkdir()
            names = {f.name for f in dlg.export_to(out).iterdir()}
            self.assertIn("文案_抖音.txt", names)
            self.assertNotIn("文案_快手.txt", names)
            win.close()
            store.close()

    def test_concurrency_limit_and_priority(self):
        app()
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp, speed=20, concurrent=1)
            win._submit([{**BRIEF, "topic": "one"}], "waiting", None)
            win._submit([{**BRIEF, "topic": "two"}], "waiting", None)
            win._submit([{**BRIEF, "topic": "three"}], "waiting", None)
            by_title = {r["title"]: r["id"] for r in store.tasks()}
            self.assertEqual(len(store.tasks_with_status("running")), 1)
            self.assertEqual(store.task(by_title["one"])["status"], "running")
            # raise "three" above "two" in the waiting queue, as a drag would
            win._handle_drop("execution", [by_title["three"]], 1)
            self.assertEqual([r["title"] for r in store.tasks_with_status("waiting")], ["three", "two"])
            self.assertTrue(pump(lambda: all(
                store.task(i)["status"] == "success" for i in by_title.values()), 30000, auto_confirm=win))
            starts = {t: store.task(i)["started"] for t, i in by_title.items()}
            self.assertLess(starts["one"], starts["three"])
            self.assertLess(starts["three"], starts["two"])
            win.close()
            store.close()

    def test_stopped_task_reruns_in_place_and_returns_to_pending(self):
        app()
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp)
            tid = store.create_task("stopped", BRIEF, status="cancelled")
            store.add_event(tid, Event("message", {"role": "agent", "text": "x"}))
            run = store.start_run(tid, "stopped", "Wan 3.0")
            store.update_run_cost(run, 0.5)
            store.finish_run(run, "cancelled")

            win._handle_drop("execution", [tid], 0)  # dropping it back into the run queue does nothing
            self.assertEqual(store.task(tid)["status"], "cancelled")

            win._handle_drop("pending", [tid], 0)  # dragging it to the to-do queue resets it
            row = store.task(tid)
            self.assertEqual((row["status"], row["total_cost"]), ("pending", 0.5))  # spending is kept
            self.assertEqual(store.events(tid), [])

            store.set_status(tid, "failed")
            win._rerun(tid)  # reruns as the same task, no duplicate
            self.assertEqual(len(store.tasks()), 1)
            self.assertEqual(store.task(tid)["status"], "running")
            self.assertTrue(pump(lambda: store.task(tid)["status"] == "success", auto_confirm=win))

            win._rerun(tid)  # a successful task is copied instead, keeping its result
            self.assertEqual(len(store.tasks()), 2)
            self.assertEqual(store.task(tid)["status"], "success")
            self.assertTrue(pump(lambda: not store.tasks_with_status("running", "waiting"), auto_confirm=win))
            self.assertEqual(len(store.runs(tid)), 2)  # the interrupted-then-rerun task has two runs
            self.assertAlmostEqual(store.task(tid)["total_cost"], 0.5 + 1.15)
            win.close()
            store.close()

    def test_cost_statistics_survive_task_deletion(self):
        app()
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp)
            now = time.time()
            a = store.create_task("a", BRIEF)
            b = store.create_task("b", BRIEF)
            for tid, title, model, cost, when in [
                    (a, "a", "Wan 3.0", 1.0, now), (a, "a", "Wan 3.0", 0.5, now - 3 * 86400),
                    (b, "b", "Seedance 2.5", 2.0, now - 40 * 86400)]:
                run = store.start_run(tid, title, model, started=when)
                store.update_run_cost(run, cost)
                store.finish_run(run, "success")
            store.delete_task(b)
            self.assertEqual(store.cost_total(0), (3, 3.5))
            self.assertEqual(store.cost_total(day_start(0)), (1, 1.0))
            self.assertEqual(store.cost_total(day_start(6)), (2, 1.5))
            self.assertEqual([r[1] for r in store.cost_by_task(0)], ["b", "a"])  # deleted task still counted
            self.assertEqual(dict((m, c) for m, _, c in store.cost_by_model(0)), {"Wan 3.0": 1.5, "Seedance 2.5": 2.0})
            win._show_stats()
            self.assertEqual(win._stats_page._cards["all"].text(), "$3.50")
            self.assertEqual(win._stats_page._cards["today"].text(), "$1.00")
            win.close()
            store.close()

    def test_legacy_cost_becomes_a_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.db"
            store = TaskStore(path)
            tid = store.create_task("old", BRIEF, status="success")
            store._db.execute("UPDATE tasks SET cost=1.15 WHERE id=?", (tid,))
            store._db.commit()
            store.close()
            store = TaskStore(path)
            self.assertEqual(len(store.runs(tid)), 1)
            self.assertAlmostEqual(store.task(tid)["total_cost"], 1.15)
            store.close()

    def test_not_satisfied_creates_a_revision_task(self):
        app()
        from hypit_desktop.ui.feedback_dialog import FeedbackDialog
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp)
            win._submit([dict(BRIEF)], "waiting", None)
            first = store.tasks()[0]["id"]
            self.assertTrue(pump(lambda: store.task(first)["status"] == "success", auto_confirm=win))
            page = win._pages[first]
            self.assertFalse(page._redo.isHidden())                       # offered once the video is done
            with mock.patch.object(FeedbackDialog, "exec", return_value=1),                     mock.patch.object(FeedbackDialog, "result_value", return_value=("结尾太平淡", 12.5)):
                win._redo(first)
            new = max(store.tasks(), key=lambda r: r["id"])
            brief = json.loads(new["brief"])
            self.assertEqual((brief["feedback"], brief["feedback_at"], brief["project_from"]), ("结尾太平淡", 12.5, first))
            self.assertIn("重做", new["title"])
            self.assertNotEqual(new["id"], first)
            pump(lambda: not store.tasks_with_status("running", "waiting"), auto_confirm=win)
            win.close()
            store.close()

    def test_close_asks_when_task_running(self):
        app()
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp, speed=1)
            win._submit([dict(BRIEF)], "waiting", None)
            self.assertEqual(len(store.tasks_with_status("running")), 1)
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No) as ask:
                event = QCloseEvent()
                win.closeEvent(event)
                self.assertTrue(ask.called)
                self.assertFalse(event.isAccepted())
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                event = QCloseEvent()
                win.closeEvent(event)
                self.assertTrue(event.isAccepted())
            pump(lambda: not win._workers, 5000)  # let the cancelled worker's last events land
            store.close()

    def test_form_rows_defaults_and_templates(self):
        app()
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp)
            form = win._new_page
            self.assertEqual(win._home_btn.text(), "返回主页")
            self.assertFalse(form._pro_box.isAncestorOf(form.model))  # model/aspect/resolution show in simple mode
            self.assertFalse(form._pro_box.isAncestorOf(form.aspect))
            self.assertFalse(form._pro_box.isAncestorOf(form.resolution))

            # default theme from the link: '<platform>_<video id>', replaced by a real title once known
            rows = form.collect()
            self.assertEqual([b["topic"] for b in rows], ["抖音_7684610633048342905"])
            self.assertEqual((rows[0]["role_image"], rows[0]["product_image"], rows[0]["background_image"]), ("", "", ""))
            form._on_title(form.url.text().strip(), "猫猫的一天")
            self.assertEqual(form.collect()[0]["topic"], "猫猫的一天")

            # default theme from a local file: its name
            video = Path(tmp) / "我的视频.mp4"
            video.write_bytes(b"x")
            form.file_radio.setChecked(True)
            form.file_path.setText(str(video))
            form._refresh_default()
            self.assertEqual(form.collect()[0]["topic"], "我的视频")

            # one task per row, images optional per column
            png = Path(tmp) / "role.png"
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(20, 20)
            pixmap.fill()
            pixmap.save(str(png))
            form.table.set_image(0, 1, str(png))
            form._add_row()
            form.table.item(1, 0).setText("第二个")
            form.table.set_image(1, 3, str(png))
            briefs = form.collect()
            self.assertEqual([(b["topic"], bool(b["role_image"]), bool(b["product_image"]), bool(b["background_image"]))
                              for b in briefs], [("我的视频", True, False, False), ("第二个", False, False, True)])
            form.table.set_image(1, 3, str(Path(tmp) / "missing.png"))
            with self.assertRaises(ValueError):
                form.collect()
            form.table.set_image(1, 3, "")

            form.pro_radio.setChecked(True)
            form.model.setCurrentText("Wan 3.0")
            form.custom_radio.setChecked(True)
            form.duration_custom.setValue(47)
            briefs = form.collect()
            self.assertEqual((briefs[0]["model"], briefs[0]["duration"], briefs[0]["mode"]),
                             ("Wan 3.0", "47 秒", "pro"))
            store.save_template("my", form.template_params())
            form.model.setCurrentText("Seedance 2.5")
            form.apply_params(store.templates()["my"])
            self.assertEqual(form.model.currentText(), "Wan 3.0")

            form.table.remove_selected_rows()  # nothing selected: no-op
            form.table.setRowCount(0)
            with self.assertRaises(ValueError):
                form.collect()
            win.close()
            store.close()

    def test_editing_a_queued_task_shows_its_images_then_resets(self):
        app()
        with tempfile.TemporaryDirectory() as tmp:
            store, settings, win = make_window(tmp)
            form = win._new_page
            brief = {**BRIEF, "topic": "待改", "product_image": "p.png"}
            tid = store.create_task("待改", brief, status="pending")
            win._open_task(tid)
            self.assertEqual(form.table.rows()[0]["topic"], "待改")
            self.assertEqual(form.table.rows()[0]["product_image"], "p.png")
            win._show_new()  # back to the home page: the edited task is no longer shown
            self.assertEqual(form.table.rows()[0]["topic"], "example.com_v")  # default theme of the shown link
            self.assertEqual(form.table.rows()[0]["product_image"], "")
            win.close()
            store.close()


if __name__ == "__main__":
    unittest.main()
