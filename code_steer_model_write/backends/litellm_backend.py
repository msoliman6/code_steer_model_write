"""The LiteLLM backend (provider-agnostic): `response_format` json_schema where the provider
honours it; the answer is validated by ask() regardless (VALIDATE_ONLY -- rule 6 is the
guarantee, not the provider)."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .base import CallResult, CallSpec, Capabilities, Fact, SchemaMode, Usage

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


class LiteLLMBackend:
    name = "litellm"

    def __init__(self, completion: Callable[..., Any] | None = None) -> None:
        self._completion = completion

    def completion(self) -> Callable[..., Any]:
        if self._completion is None:
            import litellm

            self._completion = litellm.completion
        return self._completion

    def capabilities(self) -> Capabilities:
        return Capabilities(schema_mode=SchemaMode.VALIDATE_ONLY, tools_denyable=True, streams=False)

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult:
        if call.tools:
            return CallResult(status="error", reason="the litellm backend runs tool-less steps only in v1")
        kwargs: dict[str, Any] = {
            "model": call.model,
            "messages": [{"role": "system", "content": call.system}, {"role": "user", "content": call.user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": call.schema_name, "schema": call.schema_, "strict": True},
            },
            "max_tokens": call.max_tokens,
        }
        if call.effort in ("low", "medium", "high"):
            kwargs["reasoning_effort"] = call.effort
        try:
            resp = self.completion()(**kwargs)
        except Exception as e:  # noqa: BLE001
            if "reasoning_effort" in kwargs and "reasoning" in str(e).lower():
                kwargs.pop("reasoning_effort")
                try:
                    resp = self.completion()(**kwargs)
                except Exception as e2:  # noqa: BLE001
                    return CallResult(status="error", reason=f"{type(e2).__name__}: {str(e2)[:300]}")
            else:
                return CallResult(status="error", reason=f"{type(e).__name__}: {str(e)[:300]}")
        on_fact(Fact(kind="turn", text="completion"))
        u = getattr(resp, "usage", None)
        usage = Usage(
            input_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(u, "completion_tokens", 0) or 0),
        )
        on_fact(Fact(kind="usage", data=usage.model_dump()))
        try:
            text = resp.choices[0].message.content or ""
        except (AttributeError, IndexError):
            return CallResult(status="no_output", reason="no choices in the response", usage=usage)
        m = _FENCE.match(text.strip())
        body = m.group(1) if m else text.strip()
        try:
            parsed = json.loads(body)
        except ValueError as e:
            return CallResult(
                status="no_output",
                raw_text=text,
                reason=f"the answer is not JSON: {e}",
                usage=usage,
                model_used=getattr(resp, "model", call.model),
            )
        on_fact(Fact(kind="final", text="json"))
        return CallResult(
            status="final",
            raw_text=text,
            parsed=parsed,
            usage=usage,
            model_used=getattr(resp, "model", call.model),
        )
