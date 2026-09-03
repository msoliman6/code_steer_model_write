"""The pipeline as data (rule 1): a Step is what the driver executes; a Program generates
steps from the files on disk (never from a counter), so a run resumes from where the files
say it is, and loops are bounded by data."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field

from ..artifacts.store import Store
from ..spec.base import Artifact
from ..state.run import RunPaths, RunState


class StepKind(StrEnum):
    AUTHOR = "author"  # a model call under a schema, landed by code
    RUN = "run"  # a subprocess with the exit-code contract
    CODE = "code"  # a registered python function (freeze, render, merge)
    CHECK = "check"  # a code check over artifacts; problems route by the step's policy
    GATE = "gate"  # a human (or auto) decision file


class Step(BaseModel):
    key: str
    kind: StepKind
    phase: str
    after: list[str] = Field(default_factory=list)
    # AUTHOR
    prompt: str | None = None
    schema_name: str | None = None
    role: str | None = None
    sets: dict[str, str] = Field(default_factory=dict)  # already-rendered markdown values
    rendered_keys: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    needs_tools: bool = False
    fixture: str | None = None
    check_extra: dict[str, Any] = Field(default_factory=dict)  # handed to CheckContext.extra
    land: str | None = None  # the artifact key the accepted answer is written to
    # RUN
    command: list[str] | None = None
    cwd: str | None = None
    # CODE / CHECK
    fn: str | None = None
    on_problems: str = "halt"  # halt | carry
    # GATE
    gate: str | None = None
    # proof of done, run-dir relative (rule 10: a missing deliverable reopens the step)
    deliverables: list[str] = Field(default_factory=list)
    note: str = ""  # one plain sentence for the page's now line


class Program(Protocol):
    """What a recipe gives the driver."""

    name: str
    prompts_root: Path
    fixtures_root: Path | None
    schemas: dict[str, type[Artifact]]
    code_steps: dict[str, Callable[["ProgramContext"], None]]
    checks: dict[str, Callable[["ProgramContext"], list[str]]]

    def steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Step]: ...

    def land(self, step: Step, value: Artifact, ctx: "ProgramContext") -> list[str]:
        """Code writes the accepted artifact; returns the deliverables it produced."""
        ...


class ProgramContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    state: RunState
    paths: RunPaths
    store: Store
    step: Step
    events: Any
    answer: Any = None  # the artifact under check, for an AUTHOR step's checks
    extra: dict[str, Any] = Field(default_factory=dict)
