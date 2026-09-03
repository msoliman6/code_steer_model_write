"""A recipe: a workflow as data plus a step generator (rules 1, 12).

The declarative parts (stages, gates, evals, the required checks -- the profile checklist)
are pydantic and validated at import; the step generator is code that derives steps from the
files on disk. A recipe carries an honest `status`: unproven until one clean live pass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from ..artifacts.store import Store
from ..driver.steps import ProgramContext, Step
from ..gates.gate import GateBuilder
from ..spec.base import Artifact, Problem
from ..spec.task import TaskSpec
from ..state.run import RunPaths, RunState


class CheckKind(StrEnum):
    SCHEMA = "schema"
    CITES_RESOLVE = "cites_resolve"
    BANNED_WORDS = "banned_words"
    NULL_RUN = "null_run"
    COVERAGE = "coverage"
    ENVELOPE = "envelope"
    COMPILE = "compile"
    AI_REVIEW = "ai_review"
    AI_JUDGE = "ai_judge"
    HUMAN_GATE = "human_gate"
    ACTION_ALLOWLIST = "action_allowlist"
    CITATION_VERBATIM = "citation_verbatim"
    ARBITRATION_ENGAGES = "arbitration_engages"
    ANTI_FATIGUE = "anti_fatigue"


class FigurePhrases(BaseModel):
    author: str  # "Claude writes the plan"
    checker: str | None = None  # "Codex attacks it"
    rounds: str | None = None  # "rounds", "rounds + a fresh audit"
    extra: list[str] = Field(default_factory=list)  # more boxes in the band, in order
    second_line: str | None = None


class StageSpec(BaseModel):
    id: str
    n: int
    title: str
    emoji: str
    hue: Literal["blue", "gold", "violet", "teal", "red", "slate"]
    description: str = Field(description="one paragraph, in words, for the page and the figure")
    author: str  # a role name, or "code" / "human"
    checker: str = "none"
    figure: FigurePhrases
    qualifier: str | None = None  # "TWO ISOLATED AUTHORS" -> "3 · BUILD — TWO ISOLATED AUTHORS"
    freeze_label: str | None = (
        None  # a slate, bold box after this stage's gates: "Freeze — the contract is hashed"
    )
    gates_after: list[str] = Field(default_factory=list)


class GateSpec(BaseModel):
    id: str
    after_stage: str
    kind: Literal["input", "judgment"]
    trigger: Literal["always", "exception", "conditional"]
    title: str
    figure_label: str  # "You confirm the blocks"


class EvalSpec(BaseModel):
    metric: str
    tier: Literal["code", "ai", "human"]
    target: float | None = None
    required: bool = True
    higher_is_better: bool = True


class RecipeSpec(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    name: str
    version: str
    status: Literal["proven", "unproven"]
    assumes: list[str]
    if_wrong: list[str]
    params_model: type[BaseModel]
    roles: dict[str, Literal["a", "b"]] = Field(description="role name -> side; a swap pairs one of each")
    stages: list[StageSpec]
    gates: list[GateSpec]
    evals: list[EvalSpec]
    required_checks: set[CheckKind]
    output_label: str = "src · tests · REPORT.md"
    footnote: list[str] = Field(default_factory=list)


class Recipe(ABC):
    """What the driver runs. Implements the Program protocol."""

    spec: RecipeSpec
    prompts_root: Path
    fixtures_root: Path | None = None
    schemas: dict[str, type[Artifact]]
    code_steps: dict[str, Callable[[ProgramContext], None]]
    checks: dict[str, Callable[[ProgramContext], list[str]]]

    @property
    def name(self) -> str:
        return self.spec.name

    @abstractmethod
    def steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Step]: ...

    @abstractmethod
    def land(self, step: Step, value: Artifact, ctx: ProgramContext) -> list[str]: ...

    @abstractmethod
    def gate_builders(self) -> dict[str, GateBuilder]: ...

    def fakers(self, paths: RunPaths, store: Store) -> dict[str, Callable[[Any], dict[str, Any]]]:
        return {}

    def params(self, task: TaskSpec) -> BaseModel:
        return self.spec.params_model.model_validate(task.inputs)

    def validate_task(self, task: TaskSpec) -> list[Problem]:
        """The profile gate at VALIDATED: the task fits the recipe and the recipe carries its
        required checks (a recipe that lost one is refused, by name)."""
        out: list[Problem] = []
        try:
            self.params(task)
        except Exception as e:  # noqa: BLE001
            out.append(Problem(code="params_invalid", message=str(e).splitlines()[0][:300]))
        for r in self.spec.roles:
            if r not in task.roles:
                out.append(
                    Problem(code="role_missing", message=f"the recipe needs a role named {r!r} in task.roles")
                )
        provided = set(self.checks) | {c.value for c in self.provided_checks()}
        for c in self.spec.required_checks:
            if c.value not in provided:
                out.append(
                    Problem(
                        code="required_check_missing",
                        message=f"the recipe declares {c.value} required but provides no such check",
                    )
                )
        return out

    def provided_checks(self) -> set[CheckKind]:
        """Checks the recipe provides outside `self.checks` (schema validation, semantic checks,
        the review loop's arbitration rules, gates)."""
        return set()
