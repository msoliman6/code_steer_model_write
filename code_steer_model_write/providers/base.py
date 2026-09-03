"""Model providers (docs/PLAN.md §7c): the page knows provider, model and effort and nothing
else. A provider lists its models and, per model, the efforts it supports -- dynamically where
the CLI can say (codex), from a maintained table where it cannot (Claude Code). The backend
adapters own the CLI syntax (backends/); a provider owns the catalogue."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

Discovery = Literal["dynamic", "configured"]


class ModelInfo(BaseModel):
    id: str  # the value the backend receives
    name: str  # what the page shows
    efforts: list[str] = Field(default_factory=list)
    default_effort: str | None = None


class Provider(Protocol):
    name: str
    model_discovery: Discovery
    effort_discovery: Discovery

    def list_models(self) -> list[ModelInfo]: ...

    def default_model(self) -> str: ...


def efforts_for(models: list[ModelInfo], model_id: str, fallback: list[str]) -> list[str]:
    m = next((x for x in models if x.id == model_id), None)
    return list(m.efforts) if m and m.efforts else list(fallback)


def default_effort_for(models: list[ModelInfo], model_id: str, fallback: str) -> str:
    m = next((x for x in models if x.id == model_id), None)
    return m.default_effort or (m.efforts[0] if m and m.efforts else fallback) if m else fallback
