"""Drive the real main window end to end with the real AI-director backend (offscreen, no human clicks).

Submits one task, clicks the price card's "go", waits for the video, then does 不满意,重做 and waits again.
SPENDS CREDITS (about 240 for the first video + about 50 for the redo). Needs DEEPSEEK_API_KEY in the environment.

    .\\.venv\\Scripts\\python.exe experiments\\app_e2e.py --reference <video.mp4> [--no-redo]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hypit_desktop.agent.factory import make_backend_factory  # noqa: E402
from hypit_desktop.briefs import DEFAULTS  # noqa: E402
from hypit_desktop.db import TaskStore  # noqa: E402
from hypit_desktop.publish.mock import MockPublisher  # noqa: E402
from hypit_desktop.settings import Settings  # noqa: E402
from hypit_desktop.ui.feedback_dialog import FeedbackDialog  # noqa: E402
from hypit_desktop.ui.main_window import MainWindow  # noqa: E402


def pump(window, condition, timeout_s, log):
    loop, timer = QEventLoop(), QTimer()
    timer.setInterval(500)
    seen: dict = {}

    def tick():
        for task_id, page in window._pages.items():
            for card_id, card in page._cards.items():
                if card_id.startswith("budget") and card._buttons["go"].isEnabled():
                    log(f"price card on task {task_id}: clicking 确认生成")
                    card._buttons["go"].click()
        for row in window._store.tasks():
            state = (row["status"], round(row["total_cost"] or 0, 4))
            if seen.get(row["id"]) != state:
                seen[row["id"]] = state
                log(f"task {row['id']} {row['title']!r}: {state[0]}, 已花 ${state[1]}")
        if condition():
            loop.quit()

    timer.timeout.connect(tick)
    timer.start()
    QTimer.singleShot(int(timeout_s * 1000), loop.quit)
    loop.exec()
    timer.stop()
    return condition()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--topic", default="程序员的一天")
    ap.add_argument("--feedback", default="结尾太平淡,把最后一个镜头换成更夸张的反转,其余内容保持不变")
    ap.add_argument("--no-redo", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=Path("experiments/out/app-e2e-data"))
    args = ap.parse_args()

    started = time.time()

    def log(text):
        print(f"{time.time() - started:6.0f}s {text}", flush=True)

    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    settings = Settings(data_dir / "settings.json")
    settings.set("backend", "agent")
    store = TaskStore(data_dir / "tasks.db")
    window = MainWindow(store, make_backend_factory(data_dir), MockPublisher(0), settings, data_dir, title_fetcher=None)

    brief = {**DEFAULTS, "source_type": "file", "url": str(args.reference.resolve()), "topic": args.topic,
             "model": "Seedance 2.0 Mini", "duration": "15 秒"}
    window._submit([brief], "waiting", None)
    first = max(r["id"] for r in store.tasks())
    ok = pump(window, lambda: store.task(first)["status"] in ("success", "failed", "cancelled"), 3000, log)
    row = store.task(first)
    log(f"first task finished: {row['status']} (timeout={not ok})")
    page = window._pages[first]
    log(f"redo button visible: {not page._redo.isHidden()}, publish button visible: {not page._publish.isHidden()}")
    if row["status"] != "success" or args.no_redo:
        return report(store, log)

    with mock.patch.object(FeedbackDialog, "exec", return_value=1), \
            mock.patch.object(FeedbackDialog, "result_value", return_value=(args.feedback, None)):
        window._redo(first)
    second = max(r["id"] for r in store.tasks())
    pump(window, lambda: store.task(second)["status"] in ("success", "failed", "cancelled"), 3000, log)
    log(f"redo task finished: {store.task(second)['status']}")
    return report(store, log)


def report(store, log) -> int:
    for row in store.tasks():
        runs = store.runs(row["id"])
        log(f"task {row['id']} {row['title']!r} status={row['status']} cost=${row['total_cost']:.4f} runs={len(runs)}")
        for run in runs:
            log(f"    run {dict(run)}")
    for art in store.artifacts():
        log(f"works library: {dict(art)}")
    log(f"cost total: {store.cost_total()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
