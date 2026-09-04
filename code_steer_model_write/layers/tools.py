"""L6 -- tools and integrations (ARCHITECTURE.md 7.8). The typed registry of every capability
code or a model may invoke, and the log of every invocation. It executes only through L5 and
never decides allowance (that is L9).

First implementation: the four tools the runtime already shelled out to -- git, pytest,
ruff, pyright -- registered as command tools. Every invocation writes `tool.called` and
`tool.result` events with the OpenTelemetry names, then runs inside the sandbox. The MCP
client (external servers' tools entering this registry) comes with the first recipe that
declares one."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, Field

from .sandbox import Execution, ExecutionResult, Sandbox

if TYPE_CHECKING:
    from ..events import EventLog


class ToolSpec(BaseModel):
    """What the registry knows about one tool (7.8): its schema, permissions, timeout, cost,
    and the sandbox tier it requires."""

    name: str
    description: str
    args_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)  # e.g. ["read", "write:root", "network"]
    timeout: float | None = 300
    cost: str = "free"
    tier: str = "subprocess"
    binary: str | None = None  # the executable a command tool needs on PATH


CommandBuilder = Callable[[dict[str, Any]], Execution]


class Tool(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    spec: ToolSpec
    build: CommandBuilder  # typed args -> an Execution for L5


class ToolRegistry:
    def __init__(self, sandbox: Sandbox, events: "EventLog | None" = None) -> None:
        self.sandbox = sandbox
        self.events = events
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"no tool named {name!r} in the registry")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def available(self, name: str) -> bool:
        t = self.get(name)
        return t.spec.binary is None or shutil.which(t.spec.binary) is not None

    def invoke(self, name: str, args: dict[str, Any], *, step: str | None = None) -> ExecutionResult:
        """Log before, run in the sandbox, log after. Allowance is L9's and rails are L10's;
        both are asked by the caller at the moments of section 4, not here."""
        t = self.get(name)
        ex = t.build(args)
        ex.tool = name
        ex.step = step
        if ex.timeout is None:
            ex.timeout = t.spec.timeout
        call_id = f"TC-{abs(hash((name, step, tuple(sorted(str(v) for v in args.values()))))) % 10**6:06d}"
        if self.events is not None:
            before: dict[str, Any] = {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": name,
                "gen_ai.tool.call.id": call_id,
                "tier": t.spec.tier,
            }
            self.events.append("tool.called", step=step, **before)
        r = self.sandbox.run(ex)
        if self.events is not None:
            after: dict[str, Any] = {
                "gen_ai.tool.name": name,
                "gen_ai.tool.call.id": call_id,
                "exit_code": r.exit_code,
                "seconds": r.seconds,
                "touched": len(r.touched),
                "error": None if r.exit_code == 0 else "nonzero_exit",
            }
            self.events.append("tool.result", step=step, **after)
        return r


# ---- the first four tools ---------------------------------------------------------------


def _git(args: dict[str, Any]) -> Execution:
    repo = Path(args["repo"])
    return Execution(command=["git", "-C", str(repo), *args["argv"]], root=repo, timeout=60)


def _pytest(args: dict[str, Any]) -> Execution:
    # absolute, every one: pytest runs with its own cwd and the check reads with the process's;
    # a relative junit path would land under the wrong root and read as "missing" (ledger: a
    # path compared by two conventions; live-1, live-2, live-4)
    tests_dir = Path(args["tests_dir"]).resolve()
    src_dir = Path(args["src_dir"]).resolve()
    junit = Path(args["junit"]).resolve()
    junit.parent.mkdir(parents=True, exist_ok=True)
    env = {"PYTHONPATH": str(src_dir), "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"}
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--rootdir={tests_dir.parent}",
        f"--junitxml={junit}",
        str(tests_dir),
    ]
    return Execution(
        command=cmd, root=tests_dir.parent, cwd=tests_dir.parent, env=env, timeout=args.get("timeout", 300)
    )


def _ruff(args: dict[str, Any]) -> Execution:
    files = [str(f) for f in args["files"]]
    return Execution(
        command=["ruff", *args["argv"], *files], root=Path(args.get("root", Path.cwd())), timeout=120
    )


def _pyright(args: dict[str, Any]) -> Execution:
    files = [str(f) for f in args["files"]]
    return Execution(
        command=["pyright", "--outputjson", *files], root=Path(args.get("root", Path.cwd())), timeout=300
    )


def default_registry(sandbox: Sandbox, events: "EventLog | None" = None) -> ToolRegistry:
    reg = ToolRegistry(sandbox, events)
    reg.register(
        Tool(
            spec=ToolSpec(
                name="git",
                description="git in a worktree: diff, ls-files, status, worktree",
                args_schema={"repo": "path", "argv": "list[str]"},
                permissions=["read", "write:root"],
                timeout=60,
                binary="git",
            ),
            build=_git,
        )
    )
    reg.register(
        Tool(
            spec=ToolSpec(
                name="pytest",
                description="run a test directory against a source directory, JUnit out",
                args_schema={"tests_dir": "path", "src_dir": "path", "junit": "path", "timeout": "int"},
                permissions=["read", "write:root"],
                timeout=300,
                binary=None,
            ),
            build=_pytest,
        )
    )
    reg.register(
        Tool(
            spec=ToolSpec(
                name="ruff",
                description="format or check python files",
                args_schema={"argv": "list[str]", "files": "list[path]"},
                permissions=["read", "write:root"],
                timeout=120,
                binary="ruff",
            ),
            build=_ruff,
        )
    )
    reg.register(
        Tool(
            spec=ToolSpec(
                name="pyright",
                description="type-check python files, JSON out",
                args_schema={"files": "list[path]"},
                permissions=["read"],
                timeout=300,
                binary="pyright",
            ),
            build=_pyright,
        )
    )
    return reg
