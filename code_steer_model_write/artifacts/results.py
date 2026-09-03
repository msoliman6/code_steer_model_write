"""results.json: what the runner observed, per property, over n repeats; and the ruling on a
failure, written by a fresh session of the side that did not write the failing thing."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from ..spec.base import Artifact


class PropertyResult(Artifact):
    property: str
    test: str
    real: Literal["pass", "fail", "error", "nondeterministic", "missing"]
    null: Literal["pass", "fail", "error", "missing"] = Field(
        description="against the null implementation; pass = vacuous"
    )
    runs: int = 3
    passes: int = 0
    assertion: str = Field(default="", description="the failing assertion's text, verbatim")


class Results(Artifact):
    properties: list[PropertyResult]

    @property
    def failing(self) -> list[PropertyResult]:
        return [p for p in self.properties if p.real != "pass"]

    @property
    def vacuous(self) -> list[PropertyResult]:
        return [p for p in self.properties if p.null == "pass"]


RulingVerdict = Literal["test_bug", "implementation_bug", "algorithm_defect", "contract_ambiguity"]


class Ruling(Artifact):
    id: SkipJsonSchema[str | None] = None  # R-NNNN
    property: str = Field(description="the P- id")
    question: Literal[1, 2] = Field(
        description="1: is the test wrong? 2: contract, algorithm or implementation?"
    )
    verdict: RulingVerdict
    argument: str = Field(
        min_length=40, description="engaging the clause, the test and the observed assertion"
    )
    readings: list[str] = Field(default_factory=list, description="for contract_ambiguity: the two readings")
    consequence: str = Field(description="what changes: which file, which row")
    cites: list[str] = Field(min_length=1)
