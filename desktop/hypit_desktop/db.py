"""Tasks, queue order, artifacts (the works library), templates and the featured library."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .events import Event

TERMINAL = ("success", "cancelled", "failed", "interrupted")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  brief TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  cost REAL NOT NULL DEFAULT 0,
  created REAL NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  started REAL,
  finished REAL
);
CREATE TABLE IF NOT EXISTS events (
  task_id INTEGER NOT NULL,
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
  platform TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS publishes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  state TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER,
  path TEXT NOT NULL,
  title TEXT NOT NULL,
  rating INTEGER NOT NULL DEFAULT 0,
  tags TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'undecided',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS templates (
  name TEXT PRIMARY KEY,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  task_title TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  run_no INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  cost REAL NOT NULL DEFAULT 0,
  started REAL NOT NULL,
  finished REAL
);
CREATE TABLE IF NOT EXISTS featured (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL,
  cover TEXT NOT NULL DEFAULT '',
  params TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL
);
"""

# Task rows carry the money spent over all of their runs (the legacy tasks.cost column is unused).
TASK_SELECT = ("SELECT tasks.*, (SELECT COALESCE(SUM(cost), 0) FROM runs WHERE runs.task_id = tasks.id) "
               "AS total_cost FROM tasks")

# Columns added after the first release; older databases get them via ALTER TABLE.
TASK_COLUMNS = {"position": "INTEGER NOT NULL DEFAULT 0", "started": "REAL", "finished": "REAL"}


class TaskStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(tasks)")}
        for name, ddl in TASK_COLUMNS.items():
            if name not in have:
                self._db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {ddl}")
        # Closing the app interrupts running tasks; queued ones go back to 'pending' so
        # nothing starts (and spends money) without the user releasing it again.
        now = time.time()
        self._db.execute("UPDATE runs SET status='interrupted', finished=? WHERE status='running'", (now,))
        self._db.execute("UPDATE tasks SET status='interrupted', finished=? WHERE status='running'", (now,))
        self._db.execute("UPDATE tasks SET status='pending' WHERE status='waiting'")
        # Spending recorded before runs existed becomes one run per task.
        self._db.execute(
            "INSERT INTO runs (task_id, task_title, run_no, status, cost, started, finished) "
            "SELECT id, title, 1, status, cost, COALESCE(started, created), finished FROM tasks "
            "WHERE cost > 0 AND id NOT IN (SELECT task_id FROM runs)")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- tasks -------------------------------------------------------------
    def create_task(self, title: str, brief: dict, status: str = "pending") -> int:
        position = self._db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE status=?", (status,)).fetchone()[0]
        cur = self._db.execute(
            "INSERT INTO tasks (title, brief, status, created, position) VALUES (?, ?, ?, ?, ?)",
            (title, json.dumps(brief, ensure_ascii=False), status, time.time(), position))
        self._db.commit()
        return cur.lastrowid

    def update_brief(self, task_id: int, title: str, brief: dict) -> None:
        self._db.execute("UPDATE tasks SET title=?, brief=? WHERE id=?",
                         (title, json.dumps(brief, ensure_ascii=False), task_id))
        self._db.commit()

    def rename_task(self, task_id: int, title: str) -> None:
        self._db.execute("UPDATE tasks SET title=? WHERE id=?", (title, task_id))
        self._db.commit()

    def delete_task(self, task_id: int) -> None:
        for table in ("events", "publishes"):
            self._db.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,))
        self._db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self._db.commit()

    def update_task(self, task_id: int, *, status: str | None = None) -> None:
        if status is not None:
            self.set_status(task_id, status)

    def set_status(self, task_id: int, status: str) -> None:
        now = time.time()
        if status == "running":
            self._db.execute("UPDATE tasks SET status=?, started=? WHERE id=?", (status, now, task_id))
        elif status in TERMINAL:
            self._db.execute("UPDATE tasks SET status=?, finished=? WHERE id=?", (status, now, task_id))
        else:
            self._db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
        self._db.commit()

    def move(self, task_id: int, status: str, index: int | None = None) -> None:
        """Put a task into the 'pending' or 'waiting' group at `index` (None = end)."""
        ids = [r["id"] for r in self.tasks_with_status(status) if r["id"] != task_id]
        index = len(ids) if index is None else max(0, min(index, len(ids)))
        ids.insert(index, task_id)
        for position, tid in enumerate(ids):
            self._db.execute("UPDATE tasks SET position=? WHERE id=?", (position, tid))
        self._db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
        self._db.commit()

    def reset_task(self, task_id: int) -> None:
        """Forget a stopped/failed run so the task can be queued again from scratch."""
        self._db.execute("DELETE FROM events WHERE task_id=?", (task_id,))
        self._db.execute("UPDATE tasks SET started=NULL, finished=NULL WHERE id=?", (task_id,))
        self._db.commit()

    def tasks_with_status(self, *statuses: str) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(statuses))
        return list(self._db.execute(
            f"{TASK_SELECT} WHERE status IN ({marks}) ORDER BY position, id", statuses))

    def pending_tasks(self) -> list[sqlite3.Row]:
        return self.tasks_with_status("pending")

    def execution_tasks(self) -> list[sqlite3.Row]:
        """Running first, then waiting in priority order, finished ones last."""
        def key(row):
            status = row["status"]
            if status == "running":
                return 0, row["started"] or 0, row["id"]
            if status == "waiting":
                return 1, row["position"], row["id"]
            return 2, row["finished"] or 0, row["id"]
        rows = self._db.execute(f"{TASK_SELECT} WHERE status != 'pending'")
        return sorted(rows, key=key)

    def tasks(self) -> list[sqlite3.Row]:
        return list(self._db.execute(f"{TASK_SELECT} ORDER BY id DESC"))

    def task(self, task_id: int) -> sqlite3.Row:
        return self._db.execute(f"{TASK_SELECT} WHERE id=?", (task_id,)).fetchone()

    # --- runs: one row per execution, the ledger behind all cost figures -------
    # Runs outlive their task: deleting a task keeps what it cost.
    def start_run(self, task_id: int, title: str, model: str = "", started: float | None = None) -> int:
        run_no = self._db.execute(
            "SELECT COALESCE(MAX(run_no), 0) + 1 FROM runs WHERE task_id=?", (task_id,)).fetchone()[0]
        cur = self._db.execute(
            "INSERT INTO runs (task_id, task_title, model, run_no, started) VALUES (?,?,?,?,?)",
            (task_id, title, model, run_no, time.time() if started is None else started))
        self._db.commit()
        return cur.lastrowid

    def update_run_cost(self, run_id: int, cost: float) -> None:
        self._db.execute("UPDATE runs SET cost=? WHERE id=?", (cost, run_id))
        self._db.commit()

    def finish_run(self, run_id: int, status: str) -> None:
        self._db.execute("UPDATE runs SET status=?, finished=? WHERE id=?", (status, time.time(), run_id))
        self._db.commit()

    def current_run(self, task_id: int) -> int | None:
        row = self._db.execute(
            "SELECT id FROM runs WHERE task_id=? AND status='running' ORDER BY id DESC LIMIT 1",
            (task_id,)).fetchone()
        return row["id"] if row else None

    def runs(self, task_id: int) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM runs WHERE task_id=? ORDER BY run_no", (task_id,)))

    def cost_total(self, since: float = 0) -> tuple[int, float]:
        row = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(cost), 0) FROM runs WHERE started >= ?", (since,)).fetchone()
        return row[0], row[1]

    def cost_by_task(self, since: float = 0) -> list[tuple[int, str, int, float]]:
        rows = self._db.execute(
            "SELECT task_id, MAX(task_title), COUNT(*), SUM(cost) AS c FROM runs WHERE started >= ? "
            "GROUP BY task_id ORDER BY c DESC", (since,))
        return [tuple(r) for r in rows]

    def cost_by_model(self, since: float = 0) -> list[tuple[str, int, float]]:
        rows = self._db.execute(
            "SELECT model, COUNT(*), SUM(cost) AS c FROM runs WHERE started >= ? "
            "GROUP BY model ORDER BY c DESC", (since,))
        return [tuple(r) for r in rows]

    def cost_by_day(self, since: float = 0) -> list[tuple[str, int, float]]:
        rows = self._db.execute(
            "SELECT strftime('%Y-%m-%d', started, 'unixepoch', 'localtime') AS day, COUNT(*), SUM(cost) "
            "FROM runs WHERE started >= ? GROUP BY day ORDER BY day", (since,))
        return [tuple(r) for r in rows]

    # --- events ------------------------------------------------------------
    def add_event(self, task_id: int, event: Event) -> None:
        self._db.execute("INSERT INTO events (task_id, body) VALUES (?, ?)", (task_id, event.to_json()))
        self._db.commit()

    def events(self, task_id: int) -> list[Event]:
        rows = self._db.execute("SELECT body FROM events WHERE task_id=? ORDER BY seq", (task_id,))
        return [Event.from_json(r["body"]) for r in rows]

    # --- platform accounts and publish history -------------------------------
    def authorized_platforms(self) -> set[str]:
        return {r["platform"] for r in self._db.execute("SELECT platform FROM accounts")}

    def set_authorized(self, platform: str, authorized: bool) -> None:
        if authorized:
            self._db.execute("INSERT OR IGNORE INTO accounts (platform) VALUES (?)", (platform,))
        else:
            self._db.execute("DELETE FROM accounts WHERE platform=?", (platform,))
        self._db.commit()

    def add_publish(self, task_id: int, platform: str, state: str, message: str, url: str) -> None:
        self._db.execute(
            "INSERT INTO publishes (task_id, platform, state, message, url, created) VALUES (?,?,?,?,?,?)",
            (task_id, platform, state, message, url, time.time()))
        self._db.commit()

    def publishes(self, task_id: int) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM publishes WHERE task_id=? ORDER BY id", (task_id,)))

    # --- works library -------------------------------------------------------
    def add_artifact(self, task_id: int | None, path: str, title: str) -> int:
        cur = self._db.execute(
            "INSERT INTO artifacts (task_id, path, title, created) VALUES (?,?,?,?)",
            (task_id, path, title, time.time()))
        self._db.commit()
        return cur.lastrowid

    def artifacts(self) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM artifacts ORDER BY id DESC"))

    def artifact(self, artifact_id: int) -> sqlite3.Row:
        return self._db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()

    def update_artifact(self, artifact_id: int, *, rating: int | None = None,
                        tags: str | None = None, status: str | None = None) -> None:
        for column, value in (("rating", rating), ("tags", tags), ("status", status)):
            if value is not None:
                self._db.execute(f"UPDATE artifacts SET {column}=? WHERE id=?", (value, artifact_id))
        self._db.commit()

    def delete_artifact(self, artifact_id: int) -> None:
        self._db.execute("DELETE FROM artifacts WHERE id=?", (artifact_id,))
        self._db.commit()

    # --- templates -----------------------------------------------------------
    def save_template(self, name: str, params: dict) -> None:
        self._db.execute("INSERT OR REPLACE INTO templates (name, body) VALUES (?, ?)",
                         (name, json.dumps(params, ensure_ascii=False)))
        self._db.commit()

    def templates(self) -> dict[str, dict]:
        rows = self._db.execute("SELECT name, body FROM templates ORDER BY name")
        return {r["name"]: json.loads(r["body"]) for r in rows}

    def delete_template(self, name: str) -> None:
        self._db.execute("DELETE FROM templates WHERE name=?", (name,))
        self._db.commit()

    # --- featured library ----------------------------------------------------
    def add_featured(self, platform: str, title: str, description: str, url: str,
                     cover: str, params: dict) -> int:
        cur = self._db.execute(
            "INSERT INTO featured (platform, title, description, url, cover, params, created) VALUES (?,?,?,?,?,?,?)",
            (platform, title, description, url, cover, json.dumps(params, ensure_ascii=False), time.time()))
        self._db.commit()
        return cur.lastrowid

    def update_featured(self, featured_id: int, platform: str, title: str, description: str,
                        url: str, cover: str, params: dict) -> None:
        self._db.execute(
            "UPDATE featured SET platform=?, title=?, description=?, url=?, cover=?, params=? WHERE id=?",
            (platform, title, description, url, cover, json.dumps(params, ensure_ascii=False), featured_id))
        self._db.commit()

    def delete_featured(self, featured_id: int) -> None:
        self._db.execute("DELETE FROM featured WHERE id=?", (featured_id,))
        self._db.commit()

    def featured(self) -> list[dict]:
        rows = self._db.execute("SELECT * FROM featured ORDER BY id")
        return [{**dict(r), "params": json.loads(r["params"])} for r in rows]
