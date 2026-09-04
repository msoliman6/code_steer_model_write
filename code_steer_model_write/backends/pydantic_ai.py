"""L4 first implementation (ARCHITECTURE.md 7.5): PydanticAI behind the Backend seam.

One call, one schema: the Artifact class is the agent's output type, in the provider's
native structured-output mode where it has one (constrained decoding at generation), as a
tool schema otherwise. The answer comes back as a pydantic instance; the runtime's one
validator still runs on it (rule 4), the rails still rule on it (L10), and the re-ask loop is
still the runtime's. Usage comes from every result. The typed record of the run's messages is
written to the stream path; nothing is parsed by position (section 4, L4).

Tool-using calls use the deferred-tool loop: the model emits a tool call, the run pauses,
this backend hands the call to the ToolDef's function (the L6 callback), and resumes the run
with the result -- the vendor never runs a tool (section 6, "ask with tools uses a callback").
The loop is bounded by the call's max_turns."""

from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import ValidationError

from .base import CallResult, CallSpec, Capabilities, Fact, SchemaMode, Usage

PROVIDER_DEFAULT = "anthropic"
NATIVE_OUTPUT_PROVIDERS = {
    "anthropic",
    "openai",
    "openai-chat",
    "openai-responses",
}  # constrained decoding at generation (7.5 facts)


def _model_id(name: str) -> tuple[str, str]:
    """`provider:model`, or the default provider when the model carries none."""
    if ":" in name:
        p, m = name.split(":", 1)
        return p, m
    return PROVIDER_DEFAULT, name


class PydanticAIBackend:
    name = "pydantic_ai"

    def __init__(self, model: Any = None) -> None:
        self._override = model  # a TestModel / FunctionModel in tests and walks

    def capabilities(self) -> Capabilities:
        return Capabilities(schema_mode=SchemaMode.GRAMMAR, tools_denyable=True, streams=True, threads=False)

    # ---- one call -----------------------------------------------------------------------------

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult:
        from pydantic_ai import (
            Agent,
            CallDeferred,
            DeferredToolRequests,
            DeferredToolResults,
            NativeOutput,
            ToolOutput,
        )
        from pydantic_ai.settings import ModelSettings

        schema_model = call.schema_model
        if schema_model is None:
            return CallResult(
                status="error", reason="the pydantic_ai backend needs the schema's pydantic class on the call"
            )
        provider, model_name = _model_id(call.model)
        model: Any = self._override if self._override is not None else f"{provider}:{model_name}"
        native = provider in NATIVE_OUTPUT_PROVIDERS and self._override is None
        output: Any = (
            NativeOutput(schema_model) if native else ToolOutput(schema_model, name=call.schema_name)
        )
        settings: dict[str, Any] = {"max_tokens": call.max_tokens, "timeout": float(call.stall_seconds)}
        if provider == "anthropic" and self._override is None:  # provider-specific knobs
            settings["anthropic_effort"] = call.effort  # low | medium | high
            if call.thinking:
                settings["anthropic_thinking"] = {"type": "adaptive"}
        tools_by_name = {t.name: t for t in call.tools}
        out_type: Any = [schema_model, DeferredToolRequests] if tools_by_name else output
        agent = Agent(
            model,
            output_type=out_type,
            instructions=call.system,
            model_settings=ModelSettings(**settings),
            retries=0,
            tools=[self._deferred_tool(t, CallDeferred) for t in call.tools],
        )

        facts: list[Fact] = []

        def fact(kind: str, text: str = "", **data: Any) -> None:
            f = Fact(kind=kind, text=text, data=data)  # type: ignore[arg-type]
            facts.append(f)
            del facts[:-6]
            on_fact(f)

        total = Usage(turns=0)
        t0 = time.time()
        try:
            result = agent.run_sync(call.user)
            turns = 1
            tool_calls = 0
            # the deferred-tool loop: the callback style of section 6, bounded by max_turns
            while isinstance(result.output, DeferredToolRequests):
                if turns >= call.max_turns:
                    self._usage(result, total, fact, turns, tool_calls, call)
                    return CallResult(
                        status="budget",
                        reason=f"{turns} turns, the tool loop did not finish",
                        usage=total,
                        facts=facts,
                    )
                answers: dict[str, Any] = {}
                for c in result.output.calls:
                    tool_calls += 1
                    args = (
                        c.args_as_dict()
                        if hasattr(c, "args_as_dict")
                        else (c.args if isinstance(c.args, dict) else {})
                    )
                    fact("tool", c.tool_name, tool=c.tool_name, args=args)
                    fn = tools_by_name[c.tool_name].fn
                    try:
                        answers[c.tool_call_id] = fn(**args)
                    except Exception as e:  # noqa: BLE001 -- the tool's failure is the model's next input
                        answers[c.tool_call_id] = f"error: {type(e).__name__}: {e}"
                result = agent.run_sync(
                    call.user,
                    message_history=result.all_messages(),
                    deferred_tool_results=DeferredToolResults(calls=answers),
                )
                turns += 1
            self._usage(result, total, fact, turns, tool_calls, call)
        except ValidationError as e:
            return CallResult(
                status="no_output",
                reason=f"the answer did not fit the schema at generation: {str(e)[:200]}",
                usage=total,
                facts=facts,
            )
        except Exception as e:  # noqa: BLE001 -- reported honestly, never raised past the seam
            return CallResult(
                status="error", reason=f"{type(e).__name__}: {str(e)[:300]}", usage=total, facts=facts
            )
        value = result.output
        parsed = value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)
        if call.stream_path is not None:
            call.stream_path.parent.mkdir(parents=True, exist_ok=True)
            call.stream_path.write_bytes(result.all_messages_json())  # the typed record, not stdout
        fact("final", "structured output", seconds=round(time.time() - t0, 2))
        return CallResult(
            status="final",
            raw_text=None,
            parsed=parsed,
            usage=total,
            model_used=f"{provider}:{model_name}" if self._override is None else "test",
            facts=facts,
        )

    @staticmethod
    def _deferred_tool(tool: Any, CallDeferred: Any) -> Any:
        """Every declared tool is registered with its ToolSpec's exact argument schema and a body
        that defers: the model may call it, the vendor may not run it; the call returns to this
        backend's loop and the ToolDef's function answers it (section 6)."""
        from pydantic_ai.tools import Tool

        def deferred(**kwargs: Any) -> Any:
            raise CallDeferred

        return Tool.from_schema(
            deferred, name=tool.name, description=tool.description, json_schema=tool.input_schema
        )

    @staticmethod
    def _usage(
        result: Any, total: Usage, fact: Callable[..., None], turns: int, tool_calls: int, call: CallSpec
    ) -> None:
        u = result.usage
        details = getattr(u, "details", None) or {}
        cache_read = int(details.get("cache_read_input_tokens", 0) or getattr(u, "cache_read_tokens", 0) or 0)
        usage = Usage(
            input_tokens=int(u.input_tokens or 0),
            output_tokens=int(u.output_tokens or 0),
            cache_read_tokens=cache_read,
            turns=turns,
            tool_calls=tool_calls,
        )
        total.input_tokens = usage.input_tokens
        total.output_tokens = usage.output_tokens
        total.cache_read_tokens = usage.cache_read_tokens
        total.turns = usage.turns
        total.tool_calls = usage.tool_calls
        fact("usage", **usage.model_dump())
