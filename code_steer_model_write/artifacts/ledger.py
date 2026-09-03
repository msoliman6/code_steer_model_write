"""The assumptions ledger: what recon established, with its basis and what breaks if wrong;
batch-confirmed by exception in one reply (rule 11). At most LEDGER_MAX_ROWS rows; every row
has a basis."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from ..config import LEDGER_MAX_ROWS
from ..spec.base import Artifact, CheckContext, Problem


class Assumption(Artifact):
    id: SkipJsonSchema[str | None] = None  # L-NNNN
    assumption: str = Field(min_length=8, description="one claim the plan will rest on")
    basis: str = Field(
        min_length=4, description="where it comes from: the brief, the reference, a convention"
    )
    if_wrong: str = Field(min_length=4, description="what breaks downstream")
    confirm: Literal["yes", "no", "unknown"] = Field(
        default="unknown", description="the human's answer; unknown until asked"
    )


class QueueItem(Artifact):
    question: str = Field(description="what recon could not establish, in words")
    decides: str = Field(description="what the answer decides: a block, a clause, a tolerance")


class AssumptionsLedger(Artifact):
    rows: list[Assumption] = Field(description="at most 30")
    queue: list[QueueItem] = Field(default_factory=list, description="questions for the human, batched")

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        if len(self.rows) > LEDGER_MAX_ROWS:
            out.append(
                Problem(
                    code="ledger_too_long", message=f"{len(self.rows)} rows; the bound is {LEDGER_MAX_ROWS}"
                )
            )
        return out
