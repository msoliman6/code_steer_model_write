"""L9 -- identity and authorization (ARCHITECTURE.md 7.2). "Allowed?", never "good?" or
"safe?". Deterministic, invoked at every enforcement point, the decision written before the
action it allows; a tool call with no matching policy is denied (section 4, L9).

First implementations: `RunIdentity` mints the principals from the RunSpec (the user and the
sides); `StepPolicy` encodes the rules the runtime enforced before it had a policy layer:
a side may author or judge what its step declares; no tool is allowed unless the step
declares it; a write is allowed only inside the row's ownership; a gate may be auto-signed
only when the mode says so. Cedar replaces `StepPolicy` behind this seam (phase 2)."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

import itertools

if TYPE_CHECKING:
    from ..events import EventLog
    from ..state.run import RunPaths

Action = Literal["launch", "issue", "author", "judge", "tool", "execute", "write", "gate"]


class Principal(BaseModel):
    """Who is asking: a human, a model side, or a tool. Minted, never inferred (section 6)."""

    id: str
    kind: Literal["human", "side", "tool"]
    attributes: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    id: str
    principal: str
    action: Action
    resource: str
    allow: bool
    reason: str
    policy: str  # the id of the rule that decided; the reason section 4 says must be logged

    def __bool__(self) -> bool:
        return self.allow


class Identity(Protocol):
    def user(self) -> Principal: ...
    def side(self, role: str) -> Principal: ...
    def tool(self, name: str) -> Principal: ...


class Policy(Protocol):
    def decide(
        self, principal: Principal, action: Action, resource: str, context: dict[str, Any] | None = None
    ) -> Decision: ...


class RunIdentity:
    """Principals from the RunSpec: `user:<created_by>` and `side:<role>`; tools are
    `tool:<name>`. Nothing derives a principal from a prompt."""

    def __init__(self, paths: "RunPaths | None" = None) -> None:
        self._roles: dict[str, dict[str, Any]] = {}
        self._user = "local"
        if paths is not None and paths.state.exists():
            from ..state.run import RunState

            st = RunState.load(paths)
            self._roles = {r: s.model_dump(mode="json") for r, s in st.task.roles.items()}

    def user(self) -> Principal:
        return Principal(id=f"user:{self._user}", kind="human")

    def side(self, role: str) -> Principal:
        return Principal(id=f"side:{role}", kind="side", attributes=self._roles.get(role, {}))

    def tool(self, name: str) -> Principal:
        return Principal(id=f"tool:{name}", kind="tool")


class StepPolicy:
    """The rules that were scattered through the runtime, in one place, each with an id.
    Every decision is appended as a `policy.decision` event when a log is attached."""

    RULES = {
        "P-issue": "a step is issued by the driver; any minted principal may be issued its own step",
        "P-author": "a side may author the artifact its step declares",
        "P-judge": "a side may judge an artifact only if it is not the artifact's author",
        "P-tool-declared": "a side may call a tool only if its step declared that tool",
        "P-tool-default-deny": "a tool call no rule allows is denied",
        "P-execute": "an execution is allowed inside the run's own root",
        "P-write-ownership": "a write is allowed only on a path the row may write",
        "P-gate-human": "a human may decide any gate",
        "P-gate-auto": "auto may sign a gate only when the mode dial says no human is needed",
    }

    def __init__(self, events: "EventLog | None" = None) -> None:
        self.events = events
        self._ids = itertools.count(1)

    def _decide(self, p: Principal, action: Action, resource: str, allow: bool, rule: str) -> Decision:
        d = Decision(
            id=f"PD-{next(self._ids):04d}",  # code-assigned (rule 5), per policy instance
            principal=p.id,
            action=action,
            resource=resource,
            allow=allow,
            reason=self.RULES[rule],
            policy=rule,
        )
        if self.events is not None:
            self.events.append(
                "policy.decision",
                decision=d.id,
                principal=p.id,
                action=action,
                resource=resource,
                allow=allow,
                policy=rule,
            )
        return d

    def decide(
        self, principal: Principal, action: Action, resource: str, context: dict[str, Any] | None = None
    ) -> Decision:
        c = context or {}
        if action == "issue":
            return self._decide(principal, action, resource, True, "P-issue")
        if action == "author":
            return self._decide(principal, action, resource, True, "P-author")
        if action == "judge":
            author = c.get("author")
            ok = author is None or author != principal.id
            return self._decide(principal, action, resource, ok, "P-judge")
        if action == "tool":
            declared = set(c.get("declared", ()))
            if resource in declared:
                return self._decide(principal, action, resource, True, "P-tool-declared")
            return self._decide(principal, action, resource, False, "P-tool-default-deny")
        if action == "execute":
            root = c.get("root")
            cwd = c.get("cwd")
            ok = (
                root is None
                or cwd is None
                or PurePosixPath(str(cwd)).is_relative_to(PurePosixPath(str(root)))
            )
            return self._decide(principal, action, resource, ok, "P-execute")
        if action == "write":
            allowed = {PurePosixPath(a).as_posix() for a in c.get("allowed", ())}
            ok = not allowed or PurePosixPath(resource).as_posix() in allowed
            return self._decide(principal, action, resource, ok, "P-write-ownership")
        if action == "gate":
            if principal.kind == "human":
                return self._decide(principal, action, resource, True, "P-gate-human")
            return self._decide(
                principal, action, resource, bool(c.get("auto_allowed", False)), "P-gate-auto"
            )
        if action == "launch":
            return self._decide(principal, action, resource, True, "P-issue")
        raise ValueError(f"unknown action {action!r}")
