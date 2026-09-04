"""L10 -- AI guardrails (ARCHITECTURE.md 7.4). "Safe?", never "allowed?" or "good?". Three
hooks; each returns accept, or refuse with the problems; a rail never rewrites (section 4).

First implementation `SchemaRails`: after_answer is the schema's own semantic checks plus the
step's checks (what `ask()` ran inline before the seam existed); before_prompt and
before_tool_call accept and record that they were asked, so the walk proves the hook is
wired. Guardrails AI sits behind these hooks in phase 2, with validators chosen by the
profile (P10); under the correctness profile it runs none beyond the schema."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, Sequence

from pydantic import BaseModel, Field

from ..spec.base import Artifact, CheckContext, Problem

if TYPE_CHECKING:
    from ..events import EventLog


class Verdict(BaseModel):
    hook: str
    accept: bool
    problems: list[Problem] = Field(default_factory=list)
    rail: str = "schema"

    def __bool__(self) -> bool:
        return self.accept


class Rails(Protocol):
    def before_prompt(self, text: str, *, step: str, role: str) -> Verdict: ...
    def schema_refused(self, problems: Sequence[Problem], *, step: str, role: str) -> Verdict: ...
    def after_answer(
        self, value: Artifact, ctx: CheckContext, *, step: str, role: str, checks: Sequence[Any] = ()
    ) -> Verdict: ...
    def before_tool_call(self, name: str, args: dict[str, Any], *, step: str, role: str) -> Verdict: ...


class SchemaRails:
    def __init__(self, events: "EventLog | None" = None) -> None:
        self.events = events

    def _record(self, v: Verdict, *, step: str, role: str) -> Verdict:
        if self.events is not None:
            self.events.append(
                "rail.verdict",
                step=step,
                role=role,
                hook=v.hook,
                accept=v.accept,
                rail=v.rail,
                problems=[str(p) for p in v.problems],
            )
        return v

    def before_prompt(self, text: str, *, step: str, role: str) -> Verdict:
        # model-less by decision (7.4): no scanner in phase 1; the hook exists and is recorded
        return self._record(Verdict(hook="before_prompt", accept=True, rail="none"), step=step, role=role)

    def schema_refused(self, problems: Sequence[Problem], *, step: str, role: str) -> Verdict:
        """The validator refused before any semantic check ran: still an after_answer verdict,
        so every answer has one (the walk asserts it; live-4 showed the gap)."""
        return self._record(
            Verdict(hook="after_answer", accept=False, problems=list(problems), rail="schema"),
            step=step,
            role=role,
        )

    def after_answer(
        self, value: Artifact, ctx: CheckContext, *, step: str, role: str, checks: Sequence[Any] = ()
    ) -> Verdict:
        problems: list[Problem] = list(value.semantic_problems(ctx))
        rail = "schema.semantic"
        if not problems:
            for chk in checks:
                problems = list(chk.run(value, ctx))
                if problems:
                    rail = f"check.{getattr(chk, 'name', 'check')}"
                    break
        return self._record(
            Verdict(hook="after_answer", accept=not problems, problems=problems, rail=rail),
            step=step,
            role=role,
        )

    def before_tool_call(self, name: str, args: dict[str, Any], *, step: str, role: str) -> Verdict:
        return self._record(Verdict(hook="before_tool_call", accept=True, rail="none"), step=step, role=role)
