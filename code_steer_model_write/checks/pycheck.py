"""Lint, format, type-check and compile agent-written Python by code (rule 7). Findings go back
to the author as refusals. A tool that is not installed is SKIPPED and recorded, never a
silent pass (rule 10)."""

from __future__ import annotations

import py_compile
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import RUFF_IGNORE, RUFF_SELECT
from ..layers.tools import resolve_binary
from ..spec.base import Problem


class PyCheck(BaseModel):
    problems: list[Problem] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)  # tool names that were not available

    @property
    def ok(self) -> bool:
        return not self.problems


def compile_problems(files: list[Path]) -> list[Problem]:
    out: list[Problem] = []
    for f in files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            out.append(
                Problem(code="compile", path=str(f), message=str(e.msg).strip().splitlines()[-1][:300])
            )
    return out


def _tools():
    from ..layers import current

    return current().tools


def _root(files: list[Path]) -> Path:
    return files[0].parent if files else Path.cwd()


def ruff_format(files: list[Path]) -> bool:
    if not resolve_binary("ruff"):
        return False
    _tools().invoke("ruff", {"argv": ["format", "--isolated", "-q"], "files": files, "root": _root(files)})
    return True


def ruff_problems(files: list[Path]) -> tuple[list[Problem], bool]:
    if not resolve_binary("ruff"):
        return [], False
    r = _tools().invoke(
        "ruff",
        {
            "argv": [
                "check",
                "--isolated",
                "--output-format",
                "concise",
                "--select",
                ",".join(RUFF_SELECT),
                "--ignore",
                ",".join(RUFF_IGNORE),
            ],
            "files": files,
            "root": _root(files),
        },
    )
    out: list[Problem] = []
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("Found", "All checks", "[*]")):
            continue
        loc, _, rest = ln.partition(" ")
        out.append(Problem(code="ruff", path=loc.rstrip(":"), message=rest))
    return out, True


def pyright_problems(files: list[Path]) -> tuple[list[Problem], bool]:
    if not resolve_binary("pyright"):
        return [], False
    r = _tools().invoke("pyright", {"files": files, "root": _root(files)})
    out: list[Problem] = []
    try:
        import json

        data = json.loads(r.stdout or "{}")
        for d in data.get("generalDiagnostics", []):
            if d.get("severity") == "error":
                rng = d.get("range", {}).get("start", {})
                out.append(
                    Problem(
                        code="pyright",
                        path=f"{d.get('file')}:{rng.get('line', 0) + 1}",
                        message=d.get("message", "")[:300],
                    )
                )
    except ValueError:
        out.append(
            Problem(code="pyright", message="pyright produced no JSON: " + (r.stderr or r.stdout)[:200])
        )
    return out, True


def check_python(files: list[Path], *, types: bool = True) -> PyCheck:
    res = PyCheck()
    res.problems += compile_problems(files)
    if res.problems:
        return res  # nothing else is meaningful on a file that does not parse
    if not ruff_format(files):
        res.skipped.append("ruff format")
    probs, ran = ruff_problems(files)
    res.problems += probs
    if not ran:
        res.skipped.append("ruff check")
    if types:
        probs, ran = pyright_problems(files)
        res.problems += probs
        if not ran:
            res.skipped.append("pyright")
    return res
