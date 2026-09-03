"""monitor.db -- UI-only state (rule 4): the runs index the dashboard lists, the selected run,
layout. Never a second owner of a run's status: `runs.status` is refreshed from state.json by
the reader, not written by the runtime."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..state.run import RunPaths, RunState

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    workflow_run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    recipe TEXT NOT NULL,
    run_dir TEXT NOT NULL,
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    outcome TEXT
);
CREATE TABLE IF NOT EXISTS ui_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class MonitorDb:
    def __init__(self, path: Path | str = "monitor.db") -> None:
        self.path = Path(path)
        with sqlite3.connect(self.path) as c:
            c.executescript(SCHEMA)

    def register(self, paths: RunPaths) -> None:
        st = RunState.load(paths)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO runs (workflow_run_id, task_id, recipe, run_dir, status, outcome) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(workflow_run_id) DO UPDATE SET status = excluded.status, outcome = excluded.outcome, last_seen = CURRENT_TIMESTAMP",
                (
                    st.run_id,
                    st.task.task_id,
                    st.recipe,
                    str(paths.run_dir.resolve()),
                    st.status.value,
                    st.outcome.value if st.outcome else None,
                ),
            )

    def refresh(self) -> list[dict]:
        """Re-read every registered run's state.json (the owner) and return the rows."""
        rows = self.runs()
        with sqlite3.connect(self.path) as c:
            for r in rows:
                p = RunPaths(run_dir=Path(r["run_dir"]))
                if p.state.exists():
                    st = RunState.load(p)
                    r["status"], r["outcome"] = st.status.value, (st.outcome.value if st.outcome else None)
                    c.execute(
                        "UPDATE runs SET status = ?, outcome = ?, last_seen = CURRENT_TIMESTAMP WHERE workflow_run_id = ?",
                        (r["status"], r["outcome"], r["workflow_run_id"]),
                    )
                else:
                    r["status"] = "missing"
        return rows

    def runs(self) -> list[dict]:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY registered_at DESC")]

    def get_ui(self, key: str, default=None):
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT value FROM ui_state WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_ui(self, key: str, value) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO ui_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
