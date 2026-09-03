"""A halt is a report, never a crash (rule 10): the step, the command, the reason in words,
the last facts. Resume clears it and continues at that step."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ..spec.events import now
from ..state.lock import atomic_write_text
from ..state.run import RunPaths


class HaltReason(StrEnum):
    REFUSED = "refused"  # the loop stopped: cap or no progress
    BACKEND = "backend"  # stall, scope, error from the model process
    RUN_FAILED = "run_failed"  # a RUN step exited non-zero
    CHECK_FAILED = "check_failed"  # a CHECK step found problems with policy halt
    MISSING_DELIVERABLE = "missing_deliverable"
    DOCTOR = "doctor"
    CANCELLED = "cancelled"
    BROKE = "broke"  # an exception in the driver itself


class Halt(BaseModel):
    step: str
    reason: HaltReason
    message: str
    command: list[str] | None = None
    facts: list[dict[str, Any]] = Field(default_factory=list)
    resumable: bool = True
    at: datetime = Field(default_factory=now)

    def write(self, paths: RunPaths) -> None:
        atomic_write_text(paths.halt, self.model_dump_json(indent=2))

    @classmethod
    def read(cls, paths: RunPaths) -> "Halt | None":
        if not paths.halt.exists():
            return None
        return cls.model_validate_json(paths.halt.read_text(encoding="utf-8"))

    @classmethod
    def clear(cls, paths: RunPaths) -> None:
        if paths.halt.exists():
            paths.halt.unlink()

    def line(self) -> str:
        return f"HALT at {self.step} ({self.reason}): {self.message}"
