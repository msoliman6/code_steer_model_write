"""Findings, arbitration, verdicts -- graded, id'd, cited (rules 3, 5, 7).

A reviewer files findings with a severity and the ids they cite; ids are assigned by code on
ingest. An author arbitrates each by id and re-emits the whole artifact. A Verdict is computed
by code from severities: it routes, it never guesses.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from ..config import MIN_ARGUMENT_WORDS
from .base import Artifact, CheckContext, Problem


class Severity(StrEnum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


SEVERITY_ORDER = {Severity.BLOCKING: 0, Severity.MAJOR: 1, Severity.MINOR: 2}


class Klass(StrEnum):
    """The reconcile class (after addyosmani's agent-skills): what kind of thing a finding is.
    Precedence when a finding could be two: contract_misread > actionable > tradeoff > noise."""

    CONTRACT_MISREAD = (
        "contract_misread"  # the reviewer read the input wrong; the author answers by citing it
    )
    ACTIONABLE = "actionable"  # a defect with a change that fixes it
    TRADEOFF = "tradeoff"  # a real tension with no free fix; a human may weigh it
    NOISE = "noise"  # style, taste, restatement


KLASS_ORDER = {Klass.CONTRACT_MISREAD: 0, Klass.ACTIONABLE: 1, Klass.TRADEOFF: 2, Klass.NOISE: 3}


class FindingStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    CARRIED = "carried"


class Finding(Artifact):
    id: SkipJsonSchema[str | None] = None  # F-NNNN, assigned on ingest
    severity: Severity = Field(
        description="blocking: the artifact cannot stand; major: a real defect; minor: worth a word"
    )
    cites: list[str] = Field(min_length=1, description="the ids this finding is about (they must exist)")
    kind: Literal["finding", "gap"] = Field(
        default="finding", description="gap: the input itself is silent on this; routes to the human"
    )
    klass: Klass = Field(
        default=Klass.ACTIONABLE,
        description="contract_misread: the input says otherwise, cite it; actionable: a defect with a fix; "
        "tradeoff: a tension with no free fix; noise: style or restatement",
    )
    argument: str = Field(min_length=40, description="why, engaging the cited text; a reader can check it")
    status: SkipJsonSchema[FindingStatus] = FindingStatus.OPEN
    arbitration: SkipJsonSchema[str | None] = None
    round: SkipJsonSchema[int | None] = None

    @property
    def required(self) -> bool:
        """Required to address (blocking, major) or optional (minor) -- the label on every
        review comment a human or an author reads."""
        return self.severity is not Severity.MINOR


class Findings(Artifact):
    """A review round's answer. Empty `findings` with APPROVED is allowed (rule 9: the empty
    set is a valid answer); zero findings after several rounds is weak evidence, and the
    reviewer prompt says so."""

    findings: list[Finding] = Field(description="empty means you found nothing")
    verdict: Literal["APPROVED", "REVISE"] = Field(description="REVISE iff at least one finding is filed")

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        if self.findings and self.verdict == "APPROVED":
            out.append(Problem(code="verdict_contradicts", message="APPROVED with findings filed"))
        if not self.findings and self.verdict == "REVISE":
            out.append(Problem(code="verdict_contradicts", message="REVISE with no finding"))
        for i, f in enumerate(self.findings):
            for c in f.cites:
                if c not in ctx.known_ids:
                    out.append(
                        Problem(
                            code="cite_unresolved",
                            message=f"{c} is not an id in the artifact you were given",
                            path=f"findings[{i}].cites",
                        )
                    )
        return out


class ArbitrationDecision(Artifact):
    id: str = Field(description="the finding's id, exactly as given")
    status: Literal["accepted", "rejected"]
    arbitration: str = Field(
        description="accepted: name the change made; rejected: a reason of 12+ words that engages the argument"
    )


REFUSAL_PHRASES = ("out of scope", "by design", "not a concern", "as intended", "won't fix", "will not fix")

A = TypeVar("A", bound=Artifact)


class Arbitrated(Artifact, Generic[A]):
    """The author's answer to a round: one decision per finding, and the whole revised
    artifact (never a diff)."""

    decisions: list[ArbitrationDecision]
    artifact: A

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        handed = set(ctx.extra.get("finding_ids", []))
        got = [d.id for d in self.decisions]
        if set(got) != handed:
            out.append(
                Problem(
                    code="decisions_mismatch",
                    message=f"decide exactly the findings handed to you: expected {sorted(handed)}, got {sorted(got)}",
                )
            )
        for i, d in enumerate(self.decisions):
            words = len(d.arbitration.split())
            low = d.arbitration.lower()
            if d.status == "rejected" and (
                words < MIN_ARGUMENT_WORDS or any(p in low for p in REFUSAL_PHRASES)
            ):
                out.append(
                    Problem(
                        code="arbitration_refuses",
                        path=f"decisions[{i}]",
                        message=f"a rejection must engage the argument in {MIN_ARGUMENT_WORDS}+ words; "
                        "'out of scope', 'by design', 'not a concern' are refusals to arbitrate",
                    )
                )
            if d.status == "accepted" and words < 4:
                out.append(
                    Problem(
                        code="arbitration_vague",
                        path=f"decisions[{i}]",
                        message="an acceptance names the change made",
                    )
                )
        return out


class Verdict(BaseModel):
    """Computed by code from graded findings (rule 7)."""

    findings: list[Finding]
    worst: Severity | None
    route: Literal["pass", "revise", "carry", "escalate"]

    @classmethod
    def of(
        cls, findings: list[Finding], *, escalate_at: Severity = Severity.BLOCKING, cap_reached: bool = False
    ) -> "Verdict":
        open_ = [
            f
            for f in findings
            if f.status in (FindingStatus.OPEN, FindingStatus.CARRIED, FindingStatus.ESCALATED)
        ]
        if not open_:
            return cls(findings=findings, worst=None, route="pass")
        worst = min((f.severity for f in open_), key=lambda s: SEVERITY_ORDER[s])
        if any(f.status is FindingStatus.ESCALATED for f in open_) or (
            cap_reached and SEVERITY_ORDER[worst] <= SEVERITY_ORDER[escalate_at]
        ):
            return cls(findings=findings, worst=worst, route="escalate")
        return cls(findings=findings, worst=worst, route="carry" if cap_reached else "revise")
