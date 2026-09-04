"""Ownership: what a worktree actually changed versus what its row may write (rule 2, 10).
Derived from git, never from a second list. Since the seams: git runs as an L6 tool in the
L5 sandbox, and "may this row write this path" is an L9 decision (ARCHITECTURE.md 7.2), so
every refusal here is a logged policy decision, not a bare problem."""

from __future__ import annotations

from pathlib import Path

from ..spec.base import Problem


def changed_files(worktree: Path) -> list[str]:
    from ..layers import current

    def git(*args: str) -> list[str]:
        r = current().tools.invoke("git", {"repo": worktree, "argv": list(args)})
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

    files = (
        set(git("diff", "--name-only"))
        | set(git("diff", "--name-only", "--cached"))
        | set(git("ls-files", "--others", "--exclude-standard"))
    )
    return sorted(files)


def ownership_problems(worktree: Path, allowed: list[str], *, role: str | None = None) -> list[Problem]:
    from ..layers import current

    allow = {Path(a).as_posix() for a in allowed}
    layers = current()
    who = layers.identity.side(role) if role else layers.identity.user()
    out: list[Problem] = []
    for f in changed_files(worktree):
        d = layers.policy.decide(who, "write", f, {"allowed": sorted(allow)})
        if not d:
            out.append(
                Problem(
                    code="wrote_outside_ownership",
                    message=f"{f} changed, but this row may write only {sorted(allow)}",
                )
            )
    return out
