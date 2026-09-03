"""TaskSpec -- what should happen (the user's model, extended). A TaskSpec picks a recipe,
fills its parameters, names the roles and their backends, and sets the mode and the rounds cap.
Budgets are tokens, never dollars (rule 14)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..config import ROUNDS_DEFAULT, Mode, RoleSpec


class AgentSpec(BaseModel):
    name: str
    role: str
    depends_on: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class EvaluationSpec(BaseModel):
    metric: str
    target: float | None = None
    required: bool = True


class TaskSpec(BaseModel):
    task_id: str
    objective: str
    recipe: str
    agents: list[AgentSpec] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)

    roles: dict[str, RoleSpec] = Field(default_factory=dict, description="role name -> backend/model/effort")
    swaps: list[tuple[str, str]] = Field(
        default_factory=list, description="(author_role, checker_role) pairs"
    )
    require_cross_vendor: bool = True
    mode: Mode = Mode.LIGHT
    rounds: int = Field(default=ROUNDS_DEFAULT, ge=1, le=6)

    max_runtime_minutes: int | None = None
    max_tokens_total: int | None = None
    max_llm_calls: int | None = None

    evaluations: list[EvaluationSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _swaps_cross_vendor(self) -> "TaskSpec":
        for a, b in self.swaps:
            if a not in self.roles or b not in self.roles:
                raise ValueError(f"swap ({a}, {b}) names a role not in roles")
            if a == b:
                raise ValueError(f"swap ({a}, {b}): an author never checks its own work (rule 3)")
            if (
                self.require_cross_vendor
                and self.roles[a].vendor == self.roles[b].vendor
                and self.roles[a].vendor != "fake"
            ):
                raise ValueError(
                    f"swap ({a}, {b}): same vendor {self.roles[a].vendor!r}; set require_cross_vendor=false to allow"
                )
        return self
