"""One git worktree per author (rule 2, 3): the test author's has no src/, the implementer's has
no tests/. The step that needs a clean tree makes it clean and says so (ledger: state left by
an earlier run)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def add(repo: Path, path: Path, *, branch: str) -> Path:
    if path.exists():
        remove(repo, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-B", branch, str(path), "HEAD")
    return path


def remove(repo: Path, path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)], capture_output=True, text=True
    )
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True, text=True)


def strip(path: Path, subdirs: list[str]) -> list[str]:
    """Delete the directories the author must not see; returns what was removed (asserted by a walk leg)."""
    gone: list[str] = []
    for s in subdirs:
        d = path / s
        if d.exists():
            shutil.rmtree(d)
            gone.append(s)
    return gone


def is_clean(repo: Path) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True)
    return r.returncode == 0 and not r.stdout.strip()
