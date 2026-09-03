from __future__ import annotations

from typing import Literal

import pytest
from pydantic import Field

from code_steer_model_write.spec.base import Artifact, CheckContext, Problem


class Finding(Artifact):
    severity: Literal["blocking", "major", "minor"] = Field(description="how bad it is")
    cites: list[str] = Field(min_length=1, description="ids the finding is about", examples=[["C-0001"]])
    argument: str = Field(min_length=40, description="why, engaging the text it cites")


class Findings(Artifact):
    findings: list[Finding] = Field(description="empty is allowed with APPROVED")
    verdict: Literal["APPROVED", "REVISE"]

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        for i, f in enumerate(self.findings):
            for c in f.cites:
                if c not in ctx.known_ids:
                    out.append(
                        Problem(
                            code="cite_unresolved",
                            message=f"{c} is not a known id",
                            path=f"findings[{i}].cites",
                        )
                    )
        if self.findings and self.verdict == "APPROVED":
            out.append(Problem(code="verdict_contradicts", message="APPROVED with findings filed"))
        return out


@pytest.fixture
def finding_models():
    return Finding, Findings
