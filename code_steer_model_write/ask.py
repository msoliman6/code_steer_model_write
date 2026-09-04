"""ask(): one model call under a schema, with the re-ask loop (rules 2, 6, 10, 13, 14).

Attempt 1..RE_ASK_MAX: backend -> pydantic validate (always, even on grammar backends: one
validator) -> semantic checks in order, stopping at the first that refuses -> accept. A refusal
is re-asked with the exact problems and the refused answer inlined. The loop stops early when
the problem set equals any earlier attempt's (progress vs repetition). Every attempt writes
`call.*` events from this one call site. ask() writes no artifact: the step records after
acceptance, never before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generic, Literal, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from .backends.base import Backend, CallResult, CallSpec, Fact, ToolDef, Usage
from .config import MAX_TURNS, RE_ASK_MAX, RoleSpec
from .events import EventLog
from .prompts import FilledPrompt, re_ask_suffix
from .spec.base import Artifact, CheckContext, Problem
from .layers.rails import Rails

A = TypeVar("A", bound=Artifact)


class Check(Generic[A]):
    """A named semantic check (rule 7). Subclass or wrap a function."""

    name: str = "check"

    def run(self, answer: A, ctx: CheckContext) -> list[Problem]:  # pragma: no cover - interface
        raise NotImplementedError


class FnCheck(Check[A]):
    def __init__(self, name: str, fn) -> None:
        self.name = name
        self._fn = fn

    def run(self, answer: A, ctx: CheckContext) -> list[Problem]:
        return list(self._fn(answer, ctx))


class CallContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    backend: Any  # Backend
    role_spec: RoleSpec
    events: EventLog
    step: str
    streams_dir: Path | None = None
    scope_root: Path | None = None
    check_ctx: CheckContext = CheckContext()
    fixture: str | None = None
    stall_seconds: int = 180
    re_ask_max: int = RE_ASK_MAX
    rails: Any = None  # Rails (L10); None means the default SchemaRails with no event log


class Accepted(BaseModel, Generic[A]):
    value: A
    attempts: int
    usage: Usage


class Refused(BaseModel):
    problems_by_attempt: list[list[str]]
    last_answer: dict[str, Any] | None
    reason: Literal["cap", "no_progress", "backend"]
    facts: list[Fact]
    message: str
    usage: Usage


def _schema_problems(e: ValidationError) -> list[Problem]:
    out: list[Problem] = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        out.append(
            Problem(
                code=f"schema.{err.get('type', 'invalid')}",
                message=err.get("msg", "invalid"),
                path=loc or None,
            )
        )
    return out


def ask(
    prompt: FilledPrompt,
    schema: type[A],
    *,
    role: str,
    ctx: CallContext,
    checks: Sequence[Check[A]] = (),
    tools: Sequence[ToolDef] = (),
) -> Accepted[A] | Refused:
    backend: Backend = ctx.backend
    ev = ctx.events
    history: list[set[str]] = []
    problems_by_attempt: list[list[str]] = []
    last_answer: dict[str, Any] | None = None
    total = Usage(turns=0)
    facts: list[Fact] = []
    user = prompt.user
    rails: Rails = ctx.rails
    if rails is None:
        from .layers import current

        rails = current().rails
    gate_in = rails.before_prompt(prompt.system + "\n" + prompt.user, step=ctx.step, role=role)
    if not gate_in:
        strs = [str(p) for p in gate_in.problems]
        ev.append("step.refused", step=ctx.step, role=role, attempt=0, problems=strs)
        return Refused(
            problems_by_attempt=[strs],
            last_answer=None,
            reason="cap",
            facts=[],
            message="the before_prompt rail refused the input",
            usage=total,
        )
    for attempt in range(1, ctx.re_ask_max + 1):
        if attempt > 1:
            user = prompt.user + re_ask_suffix(problems_by_attempt[-1], last_answer)
        stream = (ctx.streams_dir / f"{ctx.step}.a{attempt}.jsonl") if ctx.streams_dir else None
        call = CallSpec(
            role=role,
            model=ctx.role_spec.model,
            effort=ctx.role_spec.effort,
            thinking=ctx.role_spec.thinking,
            system=prompt.system,
            user=user,
            schema=schema.wire_schema(),
            schema_name=schema.schema_name(),
            tools=list(tools),
            max_turns=MAX_TURNS,
            stream_path=stream,
            attempt=attempt,
            stall_seconds=ctx.stall_seconds,
            scope_root=ctx.scope_root,
            fixture=ctx.fixture,
        )
        ev.append(
            "call.started",
            step=ctx.step,
            role=role,
            attempt=attempt,
            model=call.model,
            schema=call.schema_name,
            tools=[t.name for t in call.tools],
            prompt_sha=prompt.sha,
            template_hash=prompt.template_hash,
            rendered_keys=prompt.rendered_keys,
        )
        recent: list[Fact] = []

        def on_fact(f: Fact, recent: list[Fact] = recent, attempt: int = attempt) -> None:
            recent.append(f)
            del recent[:-6]
            if f.kind == "usage":
                ev.append("call.usage", step=ctx.step, role=role, attempt=attempt, **f.data)

        result: CallResult = backend.complete(call, on_fact)
        total = total + result.usage
        facts = recent or result.facts
        if result.status != "final":
            ev.append(
                "call.error",
                step=ctx.step,
                role=role,
                attempt=attempt,
                status=result.status,
                reason=result.reason,
            )
            return Refused(
                problems_by_attempt=problems_by_attempt,
                last_answer=last_answer,
                reason="backend",
                facts=facts,
                message=f"{result.status}: {result.reason}",
                usage=total,
            )
        ev.append(
            "call.final",
            step=ctx.step,
            role=role,
            attempt=attempt,
            tokens=result.usage.total,
            model_used=result.model_used,
        )
        last_answer = result.parsed
        # validate -- always, one validator (rule 4)
        problems: list[Problem]
        try:
            value = schema.model_validate(result.parsed)
            problems = []
        except ValidationError as e:
            value = None
            problems = _schema_problems(e)
            rails.schema_refused(problems, step=ctx.step, role=role)
        if not problems:
            # L10 after_answer: the schema's semantic checks, then the step's checks (rule 7)
            verdict = rails.after_answer(value, ctx.check_ctx, step=ctx.step, role=role, checks=checks)  # type: ignore[arg-type]
            problems = list(verdict.problems)
        ev.append(
            "check.result", step=ctx.step, role=role, attempt=attempt, problems=[str(p) for p in problems]
        )
        if not problems:
            return Accepted(value=value, attempts=attempt, usage=total)  # type: ignore[arg-type]
        strs = [str(p) for p in problems]
        problems_by_attempt.append(strs)
        ev.append("step.refused", step=ctx.step, role=role, attempt=attempt, problems=strs)
        pset = set(strs)
        if pset in history:
            return Refused(
                problems_by_attempt=problems_by_attempt,
                last_answer=last_answer,
                reason="no_progress",
                facts=facts,
                message=f"the same problems came back on attempt {attempt}",
                usage=total,
            )
        history.append(pset)
    return Refused(
        problems_by_attempt=problems_by_attempt,
        last_answer=last_answer,
        reason="cap",
        facts=facts,
        message=f"{ctx.re_ask_max} attempts, still refused",
        usage=total,
    )
