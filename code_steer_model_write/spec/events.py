"""The event record (rule 10). One append-only log per run, one writer, written as a side
effect of work the code had to do anyway -- never a step a model performs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

EventKind = Literal[
    "run.status",
    "run.progress",
    "step.issued",
    "step.started",
    "step.done",
    "step.refused",
    "step.undone",
    "step.skipped",
    "call.started",
    "call.usage",
    "call.final",
    "call.error",
    "call.stall",
    "call.scope",
    "check.result",
    "judge.verdict",
    "gate.asked",
    "gate.decided",
    "decision.auto",
    "finding.filed",
    "finding.decided",
    "finding.carried",
    "round.closed",
    "artifact.written",
    "halt",
    # the planes and the seams (ARCHITECTURE.md section 2, invariant 5: every decision and
    # every verdict is an event, with an id the thing it allowed carries)
    "policy.decision",
    "rail.verdict",
    "tool.called",
    "tool.result",
    "sandbox.run",
]


def now() -> datetime:
    return datetime.now(timezone.utc)


class Event(BaseModel):
    seq: int
    ts: datetime = Field(default_factory=now)
    run_id: str
    kind: EventKind
    step: str | None = None
    role: str | None = None
    attempt: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
