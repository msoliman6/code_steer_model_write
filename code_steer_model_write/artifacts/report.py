"""The report: carried items and the waste table (rules 8, 14). Written by code at the end;
nothing in it is a model's summary."""

from __future__ import annotations

from pydantic import Field

from ..spec.base import Artifact


class WasteRow(Artifact):
    side: str
    calls: int = 0
    turns: int = 0
    tool_calls: int = 0
    refused_answers: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


class Carried(Artifact):
    kind: str
    id: str
    summary: str
    from_step: str


class Report(Artifact):
    run_id: str
    recipe: str
    outcome: str
    verdict: str = Field(description="the product signal, in words")
    carried: list[Carried] = Field(default_factory=list)
    waste: list[WasteRow] = Field(default_factory=list)
    flagged_decisions: list[str] = Field(default_factory=list)
    halts: int = 0
    resumed: int = 0
