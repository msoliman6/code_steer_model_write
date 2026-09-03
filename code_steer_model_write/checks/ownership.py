"""Ownership: what a worktree actually changed versus what its row may write (rule 2, 10).
Derived from git, never from a second list."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..spec.base import Problem


def changed_files(worktree: Path) -> list[str]:
    def git(*args: str) -> list[str]:
        r = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True)
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

    files = (
        set(git("diff", "--name-only"))
        | set(git("diff", "--name-only", "--cached"))
        | set(git("ls-files", "--others", "--exclude-standard"))
    )
    return sorted(files)


def ownership_problems(worktree: Path, allowed: list[str]) -> list[Problem]:
    allow = {Path(a).as_posix() for a in allowed}
    out: list[Problem] = []
    for f in changed_files(worktree):
        if f not in allow:
            out.append(
                Problem(
                    code="wrote_outside_ownership",
                    message=f"{f} changed, but this row may write only {sorted(allow)}",
                )
            )
    return out
