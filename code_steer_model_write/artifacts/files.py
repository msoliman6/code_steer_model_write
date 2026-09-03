"""The envelope around produced code (RELIABILITY: 'JSON templates for code'). The code is a
file; the model's claim about it is JSON checked against reality: the path is the one it
owns, the steps it names are the ones its row requires."""

from __future__ import annotations

from pydantic import Field

from ..spec.base import Artifact, CheckContext, Problem


class FileOut(Artifact):
    path: str = Field(description="exactly the path you were given")
    content: str = Field(min_length=1, description="the complete file")


class AuthorReport(Artifact):
    steps: list[str] = Field(
        default_factory=list,
        description="every A- step id implemented (implementer) or every P- id tested (test author)",
    )
    notes: list[str] = Field(default_factory=list)
    blocked: bool = Field(
        default=False, description="true when the input does not let you write the file; say why in notes"
    )


class FilesAuthor(Artifact):
    files: list[FileOut] = Field(min_length=1, max_length=1)
    report: AuthorReport

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        want = ctx.extra.get("path")
        if want and self.files[0].path != want:
            out.append(
                Problem(
                    code="path_not_owned", message=f"the file must be {want!r}, not {self.files[0].path!r}"
                )
            )
        if self.report.blocked and not self.report.notes:
            out.append(
                Problem(
                    code="blocked_without_reason", message="blocked: true needs a note saying what is missing"
                )
            )
        return out


class TestManifest(Artifact):
    """property id -> test node id; the lookup that kills the substring match."""

    tests: dict[str, str] = Field(description="P-NNNN -> tests/test_x.py::test_name")
