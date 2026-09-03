"""The debate recipe's artifacts: hypotheses, cases (support and challenge), rebuttals, the
judge's ruling on a rubric. Keys by the model, ids by code (rule 5)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from ..config import MIN_ARGUMENT_WORDS
from ..ids import Prefix, next_id
from ..spec.base import Artifact, CheckContext, Problem

HEDGES = ["clearly", "obviously", "undeniably", "everyone knows", "it is well known"]


class Hypothesis(Artifact):
    id: SkipJsonSchema[str | None] = None
    key: str = Field(description="a slug unique in this answer")
    claim: str = Field(min_length=20, description="one falsifiable sentence")
    falsifier: str = Field(min_length=10, description="what observation would show it false")
    assumptions: list[str] = Field(default_factory=list)


class Hypotheses(Artifact):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)
    chosen: str = Field(description="the key of the hypothesis to debate")

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        keys = [h.key for h in self.hypotheses]
        if len(set(keys)) != len(keys):
            out.append(Problem(code="key_dup", message=f"keys must be unique: {keys}"))
        if self.chosen not in keys:
            out.append(
                Problem(code="chosen_unknown", message=f"chosen {self.chosen!r} is not a hypothesis key")
            )
        return out

    def with_ids(self, previous: "Hypotheses | None") -> "Hypotheses":
        prev = {h.key: h.id for h in previous.hypotheses if h.id} if previous else {}
        taken = list(prev.values())
        h = self.model_copy(deep=True)
        for x in h.hypotheses:
            x.id = prev.get(x.key) or next_id(Prefix.HYPOTHESIS, taken)
            taken.append(x.id)
        return h

    def chosen_id(self) -> str:
        return next(h.id or "" for h in self.hypotheses if h.key == self.chosen)


class Argument(Artifact):
    id: SkipJsonSchema[str | None] = None
    key: str
    text: str = Field(min_length=30, description="the argument, engaging the claim")
    evidence: str = Field(
        min_length=10, description="what it rests on: a fact, a mechanism, a source in the brief"
    )
    cites: list[str] = Field(
        min_length=1, description="the hypothesis id (H-...) and any argument ids it answers"
    )


class Case(Artifact):
    side: Literal["support", "challenge"]
    arguments: list[Argument] = Field(min_length=1, max_length=6)

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        want = ctx.extra.get("side")
        if want and self.side != want:
            out.append(Problem(code="wrong_side", message=f"you argue the {want} side"))
        for i, a in enumerate(self.arguments):
            for c in a.cites:
                if c not in ctx.known_ids:
                    out.append(
                        Problem(
                            code="cite_unresolved", path=f"arguments[{i}]", message=f"{c} is not a known id"
                        )
                    )
            low = a.text.lower()
            for h in HEDGES:
                if h in low:
                    out.append(
                        Problem(
                            code="banned_word",
                            path=f"arguments[{i}]",
                            message=f"'{h}' asserts instead of arguing",
                        )
                    )
        return out

    def with_ids(self, taken: list[str]) -> "Case":
        c = self.model_copy(deep=True)
        t = list(taken)
        for a in c.arguments:
            a.id = next_id(Prefix.ARGUMENT, t)
            t.append(a.id)
        return c


class RebuttalItem(Artifact):
    id: str = Field(description="the challenge argument's id, exactly as given")
    status: Literal["conceded", "rebutted"]
    text: str = Field(
        description="rebutted: 12+ words engaging the argument; conceded: what the concession changes"
    )


class Rebuttal(Artifact):
    items: list[RebuttalItem]
    revised_claim: str = Field(min_length=20, description="the claim after the concessions, in one sentence")

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        handed = set(ctx.extra.get("argument_ids", []))
        got = [i.id for i in self.items]
        if set(got) != handed:
            out.append(
                Problem(
                    code="decisions_mismatch",
                    message=f"answer exactly the challenge arguments handed to you: {sorted(handed)}, got {sorted(got)}",
                )
            )
        for i, it in enumerate(self.items):
            if it.status == "rebutted" and len(it.text.split()) < MIN_ARGUMENT_WORDS:
                out.append(
                    Problem(
                        code="arbitration_refuses",
                        path=f"items[{i}]",
                        message=f"a rebuttal engages the argument in {MIN_ARGUMENT_WORDS}+ words",
                    )
                )
        return out


class RubricScore(Artifact):
    name: str
    score: int = Field(ge=0, le=10, description="0..10")
    reason: str = Field(min_length=20)


class Ruling(Artifact):
    id: SkipJsonSchema[str | None] = None
    scores: list[RubricScore] = Field(description="one per rubric row, every row")
    verdict: Literal["supported", "refuted", "undecided"]
    argument: str = Field(min_length=40, description="the case for the verdict, citing argument ids")
    cites: list[str] = Field(min_length=1)

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        rows = ctx.extra.get("rubric", [])
        got = [s.name for s in self.scores]
        if sorted(got) != sorted(rows):
            out.append(
                Problem(code="rubric_mismatch", message=f"score every rubric row once: {rows}, got {got}")
            )
        for c in self.cites:
            if c not in ctx.known_ids:
                out.append(Problem(code="cite_unresolved", message=f"{c} is not a known id"))
        return out

    def total(self, weights: dict[str, float]) -> float:
        w = sum(weights.get(s.name, 1.0) for s in self.scores) or 1.0
        return round(sum(s.score * weights.get(s.name, 1.0) for s in self.scores) / (10 * w), 3)
