"""L10 first implementation with its tool (ARCHITECTURE.md 7.4): Guardrails AI behind the
Rails seam, in-process, no server, no model downloaded, no telemetry leaving the process.

after_answer: the answer is validated by Guardrails AI against the pydantic schema (its work on
every call), then the runtime's own semantic checks and the step's checks run as before, then
the validators the profile declares (P10). before_prompt: the model-less scanner (a regex over
instruction-override phrases) as a Guardrails validator, plus the profile's. A rail accepts
or refuses with the problems; it never rewrites (section 4)."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Sequence

from ..spec.base import Artifact, CheckContext, Problem
from .profile import CORRECTNESS, Profile
from .rails import SchemaRails, Verdict

if TYPE_CHECKING:
    from ..events import EventLog

_OVERRIDE = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|prompts?)"
    r"|you are now\s+(?:a|an|the)\s|system prompt override|reveal (?:your|the) (?:system|hidden) (?:prompt|instructions)",
    re.IGNORECASE,
)


def _guardrails():
    """Import on first use, with nothing leaving the process. Guardrails' hub telemetry is a
    singleton that builds an exporter to a vendor endpoint whether or not metrics are on; it
    is created here first, disabled, and its provider replaced by one with no processor, so no
    span is ever produced, let alone exported (section 7.1 C6: self-hosted means no traffic
    nobody asked for)."""
    from guardrails import Guard, OnFailAction, settings
    from guardrails.utils.hub_telemetry_utils import HubTelemetry
    from guardrails.validators import FailResult, PassResult, Validator, register_validator
    from opentelemetry.sdk.trace import TracerProvider

    settings.rc.enable_metrics = False
    hub = HubTelemetry(enabled=False)
    processor = getattr(hub, "_processor", None)
    if processor is not None:
        try:
            processor.shutdown()  # the batch thread stops with an empty queue
        except Exception:  # noqa: BLE001 -- a telemetry thread must never be our problem
            pass
    hub._tracer_provider = TracerProvider()  # no processor: spans are dropped on creation
    hub._tracer = hub._tracer_provider.get_tracer("gr_hub")
    hub._enabled = False
    return Guard, OnFailAction, FailResult, PassResult, Validator, register_validator


class GuardrailsRails(SchemaRails):
    tool = "guardrails-ai"

    def __init__(self, events: "EventLog | None" = None, profile: Profile = CORRECTNESS) -> None:
        super().__init__(events)
        self.profile = profile
        Guard, OnFailAction, FailResult, PassResult, Validator, register_validator = _guardrails()
        self._Guard = Guard
        self._on_fail = OnFailAction.EXCEPTION
        self._guards: dict[str, Any] = {}

        @register_validator(name="csmw/override_phrases", data_type="string")
        class OverridePhrases(Validator):  # type: ignore[misc]
            """Model-less (7.4): refuses text carrying an instruction-override phrase."""

            def validate(self, value: Any, metadata: dict[str, Any]) -> Any:
                m = _OVERRIDE.search(str(value))
                if m:
                    return FailResult(
                        error_message=f"an instruction-override phrase in the input: {m.group(0)!r}"
                    )
                return PassResult()

        validators = [OverridePhrases(on_fail=self._on_fail)]
        validators += [self._hub_validator(n) for n in profile.rails_before_prompt]
        guard = Guard()
        for v in validators:
            guard = guard.use(v)
        self._input_guard = guard
        self._answer_validators = [self._hub_validator(n) for n in profile.rails_after_answer]

    def _hub_validator(self, name: str):
        """A validator the profile names, from the Guardrails registry (installed as a package,
        no hub token). An unknown name refuses at construction, before any run."""
        from guardrails.hub import __dict__ as hub  # noqa: PLC0415

        cls = hub.get(name)
        if cls is None:
            raise RuntimeError(
                f"profile {self.profile.name!r} names a rails validator {name!r} that is not installed"
            )
        return cls(on_fail=self._on_fail)

    def _guard_for(self, schema: type[Artifact]):
        g = self._guards.get(schema.__name__)
        if g is None:
            g = self._Guard.for_pydantic(schema)
            for v in self._answer_validators:
                g = g.use(v)
            self._guards[schema.__name__] = g
        return g

    def before_prompt(self, text: str, *, step: str, role: str) -> Verdict:
        try:
            out = self._input_guard.validate(text)
            ok = bool(out.validation_passed)
            problems = (
                []
                if ok
                else [Problem(code="rail.input", message=str(out.error or "refused by the input rail"))]
            )
        except Exception as e:  # the EXCEPTION on_fail: a refusal, never a crash
            ok, problems = False, [Problem(code="rail.input", message=str(e)[:300])]
        return self._record(
            Verdict(hook="before_prompt", accept=ok, problems=problems, rail=self.tool), step=step, role=role
        )

    def after_answer(
        self, value: Artifact, ctx: CheckContext, *, step: str, role: str, checks: Sequence[Any] = ()
    ) -> Verdict:
        # 1. Guardrails AI validates the answer against the schema (and the profile's validators)
        try:
            out = self._guard_for(type(value)).validate(value.model_dump_json())
            if not out.validation_passed:
                problems = [
                    Problem(code="rail.guardrails", message=str(out.error or "refused by guardrails"))
                ]
                return self._record(
                    Verdict(hook="after_answer", accept=False, problems=problems, rail=self.tool),
                    step=step,
                    role=role,
                )
        except Exception as e:
            problems = [Problem(code="rail.guardrails", message=str(e)[:300])]
            return self._record(
                Verdict(hook="after_answer", accept=False, problems=problems, rail=self.tool),
                step=step,
                role=role,
            )
        # 2. the runtime's semantic checks and the step's checks, as before
        v = super().after_answer(value, ctx, step=step, role=role, checks=checks)
        return v

    def before_tool_call(self, name: str, args: dict[str, Any], *, step: str, role: str) -> Verdict:
        # the ToolSpec's schema check plus the L9 decision cover this (7.4); Guardrails has no tool hook
        problems: list[Problem] = []
        try:
            json.dumps(args)
        except (TypeError, ValueError) as e:
            problems.append(
                Problem(code="rail.tool_args", message=f"arguments are not JSON-serialisable: {e}")
            )
        return self._record(
            Verdict(hook="before_tool_call", accept=not problems, problems=problems, rail="toolspec"),
            step=step,
            role=role,
        )
