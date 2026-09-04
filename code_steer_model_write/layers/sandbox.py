"""L5 -- execution / sandbox (ARCHITECTURE.md 7.6). The bounded place where anything that is
not a model call runs. It is handed a command and a scope; it never chooses (section 1).

First implementation `SubprocessSandbox`: the walk tier. A root, a timeout, an explicit
environment, and the files touched under the root by a scan before and after. Resource
limits are applied when asked (`cpu_seconds`, `memory_bytes`); network is not cut, which
is why the Docker tier (phase 7) exists. Nothing enters this layer except through L6
(section 2, invariant 2)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..events import EventLog


class Execution(BaseModel):
    command: list[str]
    root: Path  # the sandbox root: cwd, and the scope every write must stay inside
    cwd: Path | None = None  # defaults to root
    env: dict[str, str] | None = None  # None: the process environment; a dict: exactly that
    timeout: float | None = None
    cpu_seconds: int | None = None
    memory_bytes: int | None = None
    network: bool = True  # the subprocess tier cannot cut it; recorded so the record is honest
    tool: str | None = None  # the L6 tool this execution belongs to
    step: str | None = None


class ExecutionResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    touched: list[str] = Field(default_factory=list)  # paths under root that changed
    timed_out: bool = False
    tier: str = "subprocess"


class Sandbox(Protocol):
    tier: str

    def run(self, ex: Execution) -> ExecutionResult: ...


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return out


class SubprocessSandbox:
    tier = "subprocess"

    def __init__(self, events: "EventLog | None" = None) -> None:
        self.events = events

    def _preexec(self, ex: Execution):
        if ex.cpu_seconds is None and ex.memory_bytes is None:
            return None
        import resource

        def fn() -> None:
            if ex.cpu_seconds is not None:
                resource.setrlimit(resource.RLIMIT_CPU, (ex.cpu_seconds, ex.cpu_seconds))
            if ex.memory_bytes is not None:
                resource.setrlimit(resource.RLIMIT_AS, (ex.memory_bytes, ex.memory_bytes))

        return fn

    def run(self, ex: Execution) -> ExecutionResult:
        cwd = ex.cwd or ex.root
        before = _snapshot(ex.root)
        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.run(
                ex.command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                env=ex.env if ex.env is not None else None,
                timeout=ex.timeout,
                preexec_fn=self._preexec(ex),
            )
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            timed_out = True
            code = 124
            out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        seconds = round(time.time() - t0, 3)
        after = _snapshot(ex.root)
        touched = sorted(k for k in after if before.get(k) != after[k]) + sorted(
            k for k in before if k not in after
        )
        r = ExecutionResult(
            exit_code=code, stdout=out, stderr=err, seconds=seconds, touched=touched, timed_out=timed_out
        )
        if self.events is not None:
            self.events.append(
                "sandbox.run",
                step=ex.step,
                tool=ex.tool,
                tier=self.tier,
                command=ex.command[:3],
                exit_code=code,
                seconds=seconds,
                touched=len(touched),
                timed_out=timed_out,
                network=ex.network,
            )
        return r


def content_hash(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def process_env(*, path: str = "/usr/bin:/bin", **extra: str) -> dict[str, str]:
    """An explicit environment for a tool: a fixed PATH and only what is named."""
    env = {"PATH": path, "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}
    env.update(extra)
    return env
