"""Questions, gates and decisions (rule 11).

A gate exists only to gather a value only the human has (input gate, early) or to make a
judgment only the human can make (judgment gate, exception-triggered). Its questions arrive
batched, pre-filled, in words. What is not asked is auto-answered and FLAGGED.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .events import now


class Question(BaseModel):
    id: str  # Q-NNNN, assigned by code
    text: str = Field(description="in words; names what the answer decides")
    kind: Literal["choice", "number", "text", "confirm"] = "confirm"
    options: list[str] = Field(default_factory=list)
    default: str = ""
    recommended: str | None = None
    risky: bool = False  # light mode asks only these
    cites: list[str] = Field(default_factory=list)
    gloss: str = ""  # the cited ids, in words, for the human


class Gate(BaseModel):
    id: str  # "<name>.r<N>"
    name: str
    round: int = 1
    kind: Literal["input", "judgment"]
    title: str
    questions: list[Question] = Field(default_factory=list)
    carried: list[dict[str, Any]] = Field(default_factory=list)  # findings in words, for the form
    can_revise: bool = True
    at: datetime = Field(default_factory=now)

    def needs_human(self, mode: str) -> bool:
        if mode == "detailed":
            return True
        if mode == "auto":
            return False
        # light: a value only the human has is always asked; a judgment only if something is risky or carried
        if self.kind == "input":
            return True
        return any(q.risky for q in self.questions) or bool(self.carried)


class Decision(BaseModel):
    question_id: str
    answer: str
    answered_by: Literal["human", "auto"]
    flagged: bool = False
    comment: str = ""


class GateDecision(BaseModel):
    gate: str
    action: Literal["proceed", "revise"]
    decisions: list[Decision] = Field(default_factory=list)
    comments: dict[str, str] = Field(default_factory=dict)  # row id -> the human's words, verbatim
    source: Literal["human", "auto"]
    at: datetime = Field(default_factory=now)

    @property
    def flagged_ids(self) -> list[str]:
        return [d.question_id for d in self.decisions if d.flagged]


class DecisionRecord(BaseModel):
    """One row of decisions.json: every answer, human or auto, in one place."""

    id: str  # D-NNNN
    gate: str
    question_id: str
    question: str
    answer: str
    answered_by: Literal["human", "auto"]
    flagged: bool
    comment: str = ""
    at: datetime = Field(default_factory=now)
