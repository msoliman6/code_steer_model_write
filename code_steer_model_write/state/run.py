"""state.json -- the one owner of run and step status (rules 1, 4, 10).

Written only under the lock. A step is done when its record says so AND its deliverables
exist; a missing deliverable reopens the step on the next `next()` (resume from disk).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field

from ..spec.events import now
from ..spec.task import TaskSpec
from .lock import atomic_write_text, locked

T = TypeVar("T")


class RunStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"  # halted honestly, resumable
    FAILED = "FAILED"  # broke
    CANCELLED = "CANCELLED"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"


class Outcome(StrEnum):
    COMPLETED = "completed"
    HALTED_HONESTLY = "halted_honestly"
    BROKE = "broke"


class StepRecord(BaseModel):
    key: str
    kind: str
    issued_at: datetime = Field(default_factory=now)
    started_at: datetime | None = None
    done_at: datetime | None = None
    attempts: int = 0
    deliverables: list[str] = Field(default_factory=list)


class CarriedRecord(BaseModel):
    kind: str  # finding | property | gap | ambiguity
    id: str
    summary: str
    from_step: str


class RunPaths(BaseModel):
    run_dir: Path

    @property
    def state(self) -> Path:
        return self.run_dir / "state.json"

    @property
    def events(self) -> Path:
        return self.run_dir / "events.jsonl"

    @property
    def halt(self) -> Path:
        return self.run_dir / "halt.json"

    @property
    def task(self) -> Path:
        return self.run_dir / "task.json"

    @property
    def decisions(self) -> Path:
        return self.run_dir / "decisions.json"

    @property
    def artifacts(self) -> Path:
        return self.run_dir / "artifacts"

    @property
    def review(self) -> Path:
        return self.run_dir / "review"

    @property
    def gates(self) -> Path:
        return self.run_dir / "gates"

    @property
    def streams(self) -> Path:
        return self.run_dir / "streams"

    @property
    def worktrees(self) -> Path:
        return self.run_dir / "worktrees"

    @property
    def undone(self) -> Path:
        return self.run_dir / "_undone"

    @property
    def report(self) -> Path:
        return self.run_dir / "report.json"

    @property
    def runner(self) -> Path:
        return self.run_dir / "runner.json"

    def resolve(self, rel: str) -> Path:
        """One normaliser at the edge: every deliverable path is run-dir relative."""
        p = Path(rel)
        if p.is_absolute():
            try:
                p = p.relative_to(self.run_dir)
            except ValueError as e:
                raise ValueError(f"path outside the run dir: {rel}") from e
        return self.run_dir / p


class RunnerRecord(BaseModel):
    """Who drives the run: written by the runner at begin, refreshed while it lives, closed at
    the end. A RUNNING state whose runner is gone is a stale run (the process died without a
    word); readers say so instead of trusting the file (ledger: an exit code that lies)."""

    pid: int
    host: str = ""
    started_at: datetime = Field(default_factory=now)
    alive_at: datetime = Field(default_factory=now)
    ended_at: datetime | None = None

    def write(self, paths: "RunPaths") -> None:
        atomic_write_text(paths.runner, self.model_dump_json(indent=2))

    @classmethod
    def read(cls, paths: "RunPaths") -> "RunnerRecord | None":
        return (
            cls.model_validate_json(paths.runner.read_text(encoding="utf-8"))
            if paths.runner.exists()
            else None
        )


def pid_alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def runner_alive(paths: "RunPaths", *, max_quiet_seconds: int = 30) -> bool:
    """True iff a runner holds this run: its record is open, its pid lives, and its heartbeat
    is fresh."""
    rec = RunnerRecord.read(paths)
    if rec is None or rec.ended_at is not None:
        return False
    if not pid_alive(rec.pid):
        return False
    return (now() - rec.alive_at).total_seconds() <= max_quiet_seconds


class RunState(BaseModel):
    run_id: str
    recipe: str
    task: TaskSpec
    status: RunStatus = RunStatus.QUEUED
    outcome: Outcome | None = None
    steps: dict[str, StepRecord] = Field(default_factory=dict)
    carried: list[CarriedRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    resumed_count: int = 0
    last_halt: str | None = None
    completed_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    # ---- persistence: only through these two ------------------------------------------

    @classmethod
    def load(cls, paths: RunPaths) -> "RunState":
        return cls.model_validate_json(paths.state.read_text(encoding="utf-8"))

    def save(self, paths: RunPaths) -> None:
        self.updated_at = now()
        with locked(paths.state):
            atomic_write_text(paths.state, self.model_dump_json(indent=2))

    @classmethod
    def update(cls, paths: RunPaths, fn: "Callable[[RunState], T]") -> "T":
        """Load, mutate, write -- under one lock, so two steps finishing at once cannot lose
        each other's records (ledger: a shared record written by parallel workers; phase 5
        runs independent steps in parallel). Every writer of a step record goes through here."""
        with locked(paths.state):
            st = cls.load(paths)
            out = fn(st)
            st.updated_at = now()
            atomic_write_text(paths.state, st.model_dump_json(indent=2))
        return out

    @classmethod
    def create(cls, paths: RunPaths, task: TaskSpec) -> "RunState":
        if paths.state.exists():
            raise FileExistsError(
                f"a run already lives at {paths.run_dir} (ledger: state left by an earlier run)"
            )
        st = cls(run_id=task.task_id, recipe=task.recipe, task=task)
        paths.run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(paths.task, task.model_dump_json(indent=2))
        st.save(paths)
        return st

    def done_keys(self) -> set[str]:
        return {k for k, r in self.steps.items() if r.done_at is not None}
