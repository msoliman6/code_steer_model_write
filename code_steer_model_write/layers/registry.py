"""The Run Registry (ARCHITECTURE.md L2, stored in L7): one SQLite index of every run across
every runs directory, so the page and the gateway list runs from all projects at once. Its
`status` is a view refreshed from each run's own `state.json`, the owner (rule 4); the
registry never writes a run's status on its own account. Standard library only, one writer at
a time by SQLite's own lock in write-ahead mode (7.7)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from ..state.run import RunPaths, RunState, runner_alive

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
    run_dir TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    recipe TEXT NOT NULL,
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    outcome TEXT,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs_dirs (
    path TEXT PRIMARY KEY,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def default_path() -> Path:
    return Path(os.environ.get("CSMW_REGISTRY", str(Path.home() / ".csmw" / "registry.db")))


class RunRegistry:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.executescript(SCHEMA)
            info = list(c.execute("PRAGMA table_info(runs)"))
            cols = {r[1] for r in info}
            pk = [r[1] for r in info if r[5]]
            if pk != ["run_dir"]:
                # an index keyed by run id: two projects each with a `live-1` collided (a key that
                # is not the identity -- the folder is). Rebuilt keyed by the folder; rows kept.
                c.executescript(
                    "ALTER TABLE runs RENAME TO runs_old;"
                    + SCHEMA.split("CREATE TABLE IF NOT EXISTS runs_dirs")[0].replace(
                        "PRAGMA journal_mode=WAL;", ""
                    )
                    + "INSERT OR IGNORE INTO runs (run_dir, run_id, task_id, recipe, registered_at, last_seen, status, outcome)"
                    " SELECT run_dir, run_id, task_id, recipe, registered_at, last_seen, status, outcome FROM runs_old;"
                    "DROP TABLE runs_old;"
                )
            elif "hidden" not in cols:  # an index made before the home page could forget a run
                c.execute("ALTER TABLE runs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")

    # ---- runs directories ---------------------------------------------------------------------

    def add_dir(self, runs_dir: Path | str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR IGNORE INTO runs_dirs (path) VALUES (?)", (str(Path(runs_dir).resolve()),))

    def dirs(self) -> list[Path]:
        with sqlite3.connect(self.path) as c:
            return [Path(r[0]) for r in c.execute("SELECT path FROM runs_dirs ORDER BY added_at")]

    # ---- runs ----------------------------------------------------------------------------------

    def register(self, paths: RunPaths) -> None:
        st = RunState.load(paths)
        self.add_dir(paths.run_dir.parent)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO runs (run_id, task_id, recipe, run_dir, status, outcome) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_dir) DO UPDATE SET status = excluded.status, outcome = excluded.outcome, last_seen = CURRENT_TIMESTAMP",
                (
                    st.run_id,
                    st.task.task_id,
                    st.recipe,
                    str(paths.run_dir.resolve()),
                    st.status.value,
                    st.outcome.value if st.outcome else None,
                ),
            )

    def scan(self) -> int:
        """Every run under every registered runs directory enters the index (a run started by
        hand, or by an older runtime, is not lost). Returns how many were seen."""
        n = 0
        for d in self.dirs():
            if not d.exists():
                continue
            for sub in d.iterdir():
                p = RunPaths(run_dir=sub)
                if p.state.exists():
                    try:
                        self.register(p)
                        n += 1
                    except Exception:  # noqa: BLE001 -- a broken run dir is skipped, never fatal to the index
                        pass
        return n

    def refresh(self) -> list[dict]:
        """Re-read every run's `state.json` (the owner) and return the rows, newest first. A
        RUNNING run whose runner is gone reads STALE, never RUNNING (ledger: an exit code that lies)."""
        rows = self.runs()
        with sqlite3.connect(self.path) as c:
            for r in rows:
                p = RunPaths(run_dir=Path(r["run_dir"]))
                if p.state.exists():
                    st = RunState.load(p)
                    status = st.status.value
                    if status == "RUNNING" and not runner_alive(p):
                        status = "STALE"
                    r["status"], r["outcome"] = status, (st.outcome.value if st.outcome else None)
                    c.execute(
                        "UPDATE runs SET status = ?, outcome = ?, last_seen = CURRENT_TIMESTAMP WHERE run_dir = ?",
                        (r["status"], r["outcome"], r["run_dir"]),
                    )
                else:
                    r["status"] = "missing"
        return rows

    def runs(self, *, hidden: bool = False) -> list[dict]:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            q = (
                "SELECT * FROM runs"
                + ("" if hidden else " WHERE hidden = 0")
                + " ORDER BY registered_at DESC"
            )
            return [dict(r) for r in c.execute(q)]

    def forget(self, run_dir: Path | str) -> None:
        """The home's "remove": the index stops listing the run; its folder is never touched, and
        a scan does not bring it back (docs/PLAN.md §7d). `remember` undoes it."""
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE runs SET hidden = 1 WHERE run_dir = ?", (str(Path(run_dir).resolve()),))

    def remember(self, run_dir: Path | str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE runs SET hidden = 0 WHERE run_dir = ?", (str(Path(run_dir).resolve()),))

    def find(self, run_id: str) -> RunPaths | None:
        with sqlite3.connect(self.path) as c:
            row = c.execute(
                "SELECT run_dir FROM runs WHERE run_dir = ? OR run_id = ? ORDER BY registered_at DESC",
                (run_id, run_id),
            ).fetchone()
        return RunPaths(run_dir=Path(row[0])) if row else None
