from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import money
from ..agent.base import AgentBackend
from ..briefs import normalize, summary_of, title_of
from ..db import TERMINAL, TaskStore
from ..events import Event
from ..publish.base import Publisher
from ..credentials import KeyStore, default_store
from ..settings import Settings
from ..video_title import fetch_title
from ..worker import AgentWorker
from .feedback_dialog import FeedbackDialog
from .library_panel import LibraryPanel
from .new_task_page import NewTaskPage
from .publish_dialog import PublishDialog
from .runs_dialog import RunsDialog
from .settings_dialog import SettingsDialog
from .stats_page import StatsPage
from .task_lists import RESETTABLE, STATUS_LABELS, TaskListWidget
from .task_page import TaskPage


class MainWindow(QWidget):
    def __init__(self, store: TaskStore, backend_factory: Callable[[Settings], AgentBackend],
                 publisher: Publisher, settings: Settings, data_dir: Path,
                 title_fetcher: Optional[Callable[[str], Optional[str]]] = fetch_title,
                 credentials: Optional[KeyStore] = None):
        super().__init__()
        self.setWindowTitle("视频复刻助手")
        self.resize(1280, 900)
        self._store = store
        self._backend_factory = backend_factory
        self._publisher = publisher
        self._settings = settings
        money.configure(settings.get("display_currency"))
        self._credentials = credentials if credentials is not None else default_store()
        self._pages: dict[int, TaskPage] = {}
        self._workers: dict[int, AgentWorker] = {}
        self._selected_id: int | None = None

        # --- left: the two queues ---
        new_btn = QPushButton("返回主页")
        self._home_btn = new_btn
        new_btn.clicked.connect(self._show_new)
        self._pending = TaskListWidget()
        self._execution = TaskListWidget()
        self._pending.currentItemChanged.connect(partial(self._on_select, self._pending))
        self._execution.currentItemChanged.connect(partial(self._on_select, self._execution))
        self._pending.dropped.connect(partial(self._handle_drop, "pending"))
        self._execution.dropped.connect(partial(self._handle_drop, "execution"))
        for lst in (self._pending, self._execution):
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(partial(self._task_menu, lst))
        self._run_btn = QPushButton("▶ 加入执行队列")
        self._run_btn.clicked.connect(self._run_selected_pending)
        self._stop_btn = QPushButton("■ 停止所选任务")
        self._stop_btn.clicked.connect(self._stop_selected)
        stats_btn = QPushButton("花费统计")
        stats_btn.clicked.connect(self._show_stats)
        settings_btn = QPushButton("设置")
        settings_btn.clicked.connect(self._open_settings)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(new_btn)
        side_layout.addWidget(QLabel("待执行队列(可拖动排序,拖到下方开始)"))
        side_layout.addWidget(self._pending, 1)
        side_layout.addWidget(self._run_btn)
        side_layout.addWidget(QLabel("执行队列(排队中的可拖动调整优先级)"))
        side_layout.addWidget(self._execution, 2)
        side_layout.addWidget(self._stop_btn)
        side_layout.addWidget(stats_btn)
        side_layout.addWidget(settings_btn)

        self._new_page = NewTaskPage(store, title_fetcher)
        self._new_page.submitted.connect(self._submit)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._new_page)
        self._stats_page = StatsPage(store)
        self._stack.addWidget(self._stats_page)

        top = QSplitter()
        top.addWidget(side)
        top.addWidget(self._stack)
        top.setStretchFactor(1, 1)
        top.setSizes([300, 980])

        self._library = LibraryPanel(store, data_dir / "thumbs")
        self._library.publish_requested.connect(self._publish_artifact)
        self._library.open_task_requested.connect(self._open_task)

        rows = QSplitter(Qt.Vertical)
        rows.addWidget(top)
        rows.addWidget(self._library)
        rows.setStretchFactor(0, 1)
        rows.setSizes([640, 260])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(rows)

        self._reload_lists()

    # --- lists and selection -------------------------------------------------------
    def _reload_lists(self) -> None:
        self._pending.set_tasks(self._store.pending_tasks(), self._selected_id)
        self._execution.set_tasks(self._store.execution_tasks(), self._selected_id)
        row = self._store.task(self._selected_id) if self._selected_id else None
        self._run_btn.setEnabled(row is not None and row["status"] == "pending")
        self._stop_btn.setEnabled(row is not None and row["status"] == "running")

    def _on_select(self, source: TaskListWidget, item, *_) -> None:
        if item is None:
            return
        other = self._execution if source is self._pending else self._pending
        other.blockSignals(True)
        other.setCurrentItem(None)
        other.blockSignals(False)
        self._open_task(item.data(Qt.UserRole))

    def _open_task(self, task_id: int, *_) -> None:
        row = self._store.task(task_id)
        if row is None:
            return
        self._selected_id = task_id
        self._reload_lists()
        if row["status"] == "pending":
            self._new_page.set_edit(task_id, json.loads(row["brief"]))
            self._stack.setCurrentWidget(self._new_page)
        else:
            self._stack.setCurrentWidget(self._page_for(task_id))

    def _show_new(self) -> None:
        self._selected_id = None
        self._reload_lists()
        self._new_page.set_new()
        self._stack.setCurrentWidget(self._new_page)

    def _show_stats(self) -> None:
        self._selected_id = None
        self._reload_lists()
        self._stats_page.refresh()
        self._stack.setCurrentWidget(self._stats_page)

    def _refresh_costs(self, task_id: int) -> None:
        page = self._pages.get(task_id)
        if page is None:
            return
        runs = self._store.runs(task_id)
        page.set_costs(runs[-1]["cost"] if runs else 0.0, sum(r["cost"] for r in runs), len(runs))

    def _page_for(self, task_id: int) -> TaskPage:
        page = self._pages.get(task_id)
        if page is not None:
            return page
        row = self._store.task(task_id)
        page = self._make_page(task_id, row["title"], json.loads(row["brief"]))
        for ev in self._store.events(task_id):
            page.apply_event(ev)
        if row["status"] == "waiting":
            page.set_waiting()
        elif row["status"] not in ("success", "cancelled", "failed", "running"):
            page.set_finished(STATUS_LABELS.get(row["status"], row["status"]))
        self._refresh_costs(task_id)
        return page

    def _make_page(self, task_id: int, title: str, brief: dict) -> TaskPage:
        page = TaskPage(title, summary_of(brief))
        page.confirm_answered.connect(partial(self._answer, task_id))
        page.cancel_requested.connect(partial(self._cancel_worker, task_id))
        page.rerun_requested.connect(partial(self._rerun, task_id))
        page.runs_requested.connect(partial(self._show_runs, task_id))
        page.redo_requested.connect(partial(self._redo, task_id))
        page.publish_requested.connect(partial(self._publish_from_page, task_id))
        self._pages[task_id] = page
        self._stack.addWidget(page)
        return page

    def _answer(self, task_id: int, confirm_id: str, choice: str) -> None:
        worker = self._workers.get(task_id)
        if worker is not None:
            worker.answer(confirm_id, choice)

    def _show_runs(self, task_id: int, *_) -> None:
        RunsDialog(self._store, task_id, self).exec()

    def _redo(self, task_id: int, *_) -> None:
        """'Not satisfied': a new task that revises the finished one with the user's feedback."""
        row = self._store.task(task_id)
        dialog = FeedbackDialog(row["title"], parent=self)
        if not dialog.exec():  # 0 = cancelled
            return
        text, at = dialog.result_value()
        brief = json.loads(row["brief"])
        brief.update(feedback=text, feedback_at=at, project_from=brief.get("project_from") or task_id)
        new_id = self._store.create_task(f"{row['title']}(重做)", brief, status="waiting")
        self._schedule()
        self._open_task(new_id)

    def _publish_from_page(self, task_id: int, video_path: str) -> None:
        self._open_publish(task_id, video_path, self._store.task(task_id)["title"])

    # --- creating and moving tasks ---------------------------------------------------
    def _submit(self, briefs: list, destination: str, edit_id) -> None:
        ids = []
        for i, brief in enumerate(briefs):
            if edit_id is not None and i == 0:
                self._store.update_brief(edit_id, title_of(brief), brief)
                self._store.move(edit_id, destination)
                ids.append(edit_id)
            else:
                ids.append(self._store.create_task(title_of(brief), brief, status=destination))
        if destination == "waiting":
            self._schedule()
            self._open_task(ids[0])
            return
        self._selected_id = None
        self._reload_lists()
        self._new_page.reset_rows()
        self._new_page.set_new(f"已加入待执行队列({len(ids)} 个任务)。确认后可拖到执行队列开始。")
        self._stack.setCurrentWidget(self._new_page)

    def _run_selected_pending(self) -> None:
        if self._selected_id is None:
            return
        row = self._store.task(self._selected_id)
        if row is not None and row["status"] == "pending":
            self._store.move(row["id"], "waiting")
            self._schedule()
            self._open_task(row["id"])

    def _handle_drop(self, group: str, ids: list, row: int) -> None:
        task_id = ids[0]
        task = self._store.task(task_id)
        if task is None:
            return
        status = task["status"]
        if status not in ("pending", "waiting") + RESETTABLE:
            return  # running and successfully finished tasks cannot be moved
        lst = self._pending if group == "pending" else self._execution
        before = [(tid, s) for tid, s in lst.task_ids()[:row] if tid != task_id]
        if status in RESETTABLE and group != "pending":
            return  # a stopped task re-enters via the to-do queue or "rerun", not by dropping in place
        if group == "pending":
            self._forget_run(task_id)
            self._store.move(task_id, "pending", len(before))
            self._reload_lists()
        else:
            self._store.move(task_id, "waiting", sum(1 for _, s in before if s == "waiting"))
            self._schedule()

    # --- running ------------------------------------------------------------------------
    def _schedule(self) -> None:
        """Start waiting tasks, in priority order, while there are free slots."""
        limit = int(self._settings.get("max_concurrent"))
        running = len(self._store.tasks_with_status("running"))
        for row in self._store.tasks_with_status("waiting"):
            if running >= limit:
                break
            self._launch(row["id"])
            running += 1
        self._reload_lists()

    def _launch(self, task_id: int) -> None:
        row = self._store.task(task_id)
        brief = json.loads(row["brief"])
        self._store.set_status(task_id, "running")
        page = self._pages.get(task_id) or self._make_page(task_id, row["title"], brief)
        page.set_running()
        self._store.start_run(task_id, row["title"], normalize(brief)["model"])
        self._refresh_costs(task_id)
        worker = AgentWorker(self._backend_factory(self._settings),
                             {**normalize(brief), "task_id": task_id}, self)
        worker.event.connect(partial(self._on_event, task_id))
        worker.finished.connect(partial(self._on_worker_finished, task_id))
        self._workers[task_id] = worker
        worker.start()

    def _on_event(self, task_id: int, ev: Event) -> None:
        self._store.add_event(task_id, ev)
        self._pages[task_id].apply_event(ev)
        if ev.type == "cost":
            run_id = self._store.current_run(task_id)
            if run_id is not None:
                self._store.update_run_cost(run_id, ev.data["usd"])
            self._refresh_costs(task_id)
            self._reload_lists()
        elif ev.type == "artifact" and ev.data.get("kind") == "video":
            self._store.add_artifact(task_id, ev.data["path"], self._store.task(task_id)["title"])
            self._library.refresh()
        elif ev.type in ("done", "error"):
            status = "failed" if ev.type == "error" else ev.data["status"]
            run_id = self._store.current_run(task_id)
            if run_id is not None:
                self._store.finish_run(run_id, status)
            self._store.update_task(task_id, status=status)
            self._refresh_costs(task_id)
            self._schedule()

    def _on_worker_finished(self, task_id: int) -> None:
        self._workers.pop(task_id, None)
        row = self._store.task(task_id)
        if row is not None and row["status"] == "running":  # backend ended without done/error
            self._on_event(task_id, Event("error", {"text": "任务意外结束,没有返回结果。"}))

    def _cancel_worker(self, task_id: int, *_) -> None:
        worker = self._workers.get(task_id)
        if worker is not None:
            worker.cancel()

    def _stop_selected(self) -> None:
        if self._selected_id is not None:
            self._cancel_worker(self._selected_id)

    def _forget_run(self, task_id: int) -> None:
        """Wipe the record of a stopped/failed run (events, cost, page) before it is queued again."""
        if self._store.task(task_id)["status"] not in RESETTABLE:
            return
        self._store.reset_task(task_id)
        page = self._pages.pop(task_id, None)
        if page is not None:
            self._stack.removeWidget(page)
            page.deleteLater()

    def _rerun(self, task_id: int, *_) -> None:
        """A stopped/failed task runs again as itself; a successful one is copied, keeping its result."""
        if self._store.task(task_id)["status"] in RESETTABLE:
            self._forget_run(task_id)
            self._store.move(task_id, "waiting")
            target = task_id
        else:
            brief = json.loads(self._store.task(task_id)["brief"])
            target = self._store.create_task(title_of(brief), brief, status="waiting")
        self._schedule()
        self._open_task(target)

    # --- context menu and task actions ---------------------------------------------------
    def _task_menu(self, lst: TaskListWidget, pos, *_) -> None:
        item = lst.itemAt(pos)
        if item is None:
            return
        task_id = item.data(Qt.UserRole)
        status = self._store.task(task_id)["status"]
        menu = QMenu(self)
        if status == "pending":
            menu.addAction("编辑", partial(self._open_task, task_id))
            menu.addAction("加入执行队列", partial(self._move_to_run, task_id))
        elif status == "waiting":
            menu.addAction("移回待执行队列", partial(self._move_to_pending, task_id))
        elif status == "running":
            menu.addAction("停止", partial(self._cancel_worker, task_id))
        elif status in RESETTABLE:
            menu.addAction("重新运行", partial(self._rerun, task_id))
            menu.addAction("移回待执行队列", partial(self._move_to_pending, task_id))
        elif status in TERMINAL:
            menu.addAction("再生成一个(复制为新任务)", partial(self._rerun, task_id))
        menu.addAction("重命名", partial(self._rename, task_id))
        delete = menu.addAction("删除", partial(self._delete, task_id))
        delete.setEnabled(status != "running")
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _move_to_run(self, task_id: int, *_) -> None:
        self._store.move(task_id, "waiting")
        self._schedule()

    def _move_to_pending(self, task_id: int, *_) -> None:
        self._forget_run(task_id)
        self._store.move(task_id, "pending")
        self._reload_lists()

    def _rename(self, task_id: int, *_) -> None:
        old = self._store.task(task_id)["title"]
        title, ok = QInputDialog.getText(self, "重命名", "任务名称", text=old)
        title = title.strip()
        if not ok or not title:
            return
        self._store.rename_task(task_id, title)
        if task_id in self._pages:
            self._pages[task_id].set_title(title)
        self._reload_lists()

    def _delete(self, task_id: int, *_) -> None:
        title = self._store.task(task_id)["title"]
        answer = QMessageBox.question(
            self, "删除任务", f"确定删除「{title}」吗?任务记录将被清除;作品库里的成品、已导出的文件和花费统计不受影响。")
        if answer != QMessageBox.Yes:
            return
        page = self._pages.pop(task_id, None)
        if page is not None:
            self._stack.removeWidget(page)
            page.deleteLater()
        self._store.delete_task(task_id)
        self._show_new()

    # --- publishing and settings -------------------------------------------------------------
    def _open_publish(self, task_id: int, video_path: str, title: str) -> None:
        PublishDialog(self._store, self._publisher, task_id, video_path, title, self, self._settings).exec()

    def _publish_artifact(self, artifact_id: int) -> None:
        art = self._store.artifact(artifact_id)
        if art is not None:
            self._open_publish(art["task_id"] or 0, art["path"], art["title"])

    def _open_settings(self) -> None:
        SettingsDialog(self._settings, self._credentials, self).exec()
        self._schedule()  # a higher concurrency limit may free slots

    def closeEvent(self, event) -> None:
        if self._store.tasks_with_status("running"):
            answer = QMessageBox.question(self, "关闭应用", "有任务进行中,是否确认关闭?",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        for worker in list(self._workers.values()):
            worker.cancel()
            worker.wait(2000)
        super().closeEvent(event)
