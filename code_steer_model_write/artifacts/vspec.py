"""The verification spec: properties that cite clauses, written by the side that will not
write the code, from the test-visible view alone (rule 3). Ids P- by code."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from ..ids import Prefix, next_id
from ..spec.base import Artifact, CheckContext, Problem

PropertyClass = Literal[
    1, 2, 3, 4, 5, 6, 7
]  # schema, causality/containment, determinism, resource, leak, degeneracy, past failures


class Property(Artifact):
    id: SkipJsonSchema[str | None] = None
    cites: list[str] = Field(min_length=1, description="clause ids (C-....) this property is derived from")
    over: Literal["input", "output"] = Field(description="input: an empty output cannot satisfy it")
    klass: PropertyClass | None = Field(
        default=None,
        description="1 schema, 2 causality/containment, 3 determinism, 4 resource, 5 leak, 6 degeneracy, 7 past failure",
    )
    family: str = Field(min_length=4, description="the input family, never a fixture")
    boundary: str = Field(default="", description="the edge case in that family")
    observe: str = Field(min_length=6, description="what is measured")
    falsifies: str = Field(min_length=6, description="the condition that shows the clause false; reachable")
    tolerance: list[str] = Field(default_factory=list, description="tolerance clause ids, or empty for exact")


class ContractGap(Artifact):
    id: SkipJsonSchema[str | None] = None
    cites: list[str] = Field(
        description="the clause ids the gap is about (may be empty when a clause is missing)"
    )
    text: str = Field(min_length=20, description="what the test-visible contract does not let you decide")


class VerificationSpec(Artifact):
    properties: list[Property] = Field(min_length=1)
    contract_gaps: list[ContractGap] = Field(default_factory=list)

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        for i, p in enumerate(self.properties):
            for c in p.cites + p.tolerance:
                if c not in ctx.known_ids:
                    out.append(
                        Problem(
                            code="cite_unresolved", path=f"properties[{i}]", message=f"{c} is not a clause id"
                        )
                    )
        if not any(p.over == "input" for p in self.properties):
            out.append(
                Problem(
                    code="all_over_output",
                    message="every property quantifies over the output: an empty output passes them all; add one over the input",
                )
            )
        return out

    def with_ids(self, taken: list[str]) -> "VerificationSpec":
        v = self.model_copy(deep=True)
        t = list(taken)
        for p in v.properties:
            p.id = next_id(Prefix.PROPERTY, t)
            t.append(p.id)
        for g in v.contract_gaps:
            g.id = next_id(Prefix.GAP, t)
            t.append(g.id)
        return v
