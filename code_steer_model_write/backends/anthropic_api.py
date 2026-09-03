"""The Anthropic SDK backend: the schema in `output_config.format` (a grammar at generation),
no tools, streaming so long answers never hit a timeout (rule 2, 14)."""

from __future__ import annotations

import json
from typing import Any, Callable

from .base import CallResult, CallSpec, Capabilities, Fact, SchemaMode, Usage


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def capabilities(self) -> Capabilities:
        return Capabilities(schema_mode=SchemaMode.GRAMMAR, tools_denyable=True, streams=True)

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult:
        if call.tools:
            return CallResult(status="error", reason="the anthropic backend runs tool-less steps only in v1")
        kwargs: dict[str, Any] = {
            "model": call.model,
            "max_tokens": call.max_tokens,
            "system": call.system,
            "messages": [{"role": "user", "content": call.user}],
            "output_config": {
                "format": {"type": "json_schema", "schema": call.schema_},
                "effort": call.effort or "medium",
            },
        }
        if call.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        try:
            with self.client().messages.stream(**kwargs) as stream:
                for event in stream:
                    et = getattr(event, "type", "")
                    if et == "content_block_start":
                        bt = getattr(event.content_block, "type", "")
                        on_fact(Fact(kind="thinking" if bt == "thinking" else "turn", text=bt))
                    elif et == "message_delta":
                        on_fact(Fact(kind="heartbeat"))
                msg = stream.get_final_message()
        except Exception as e:  # noqa: BLE001 -- the vendor's error is the reason, verbatim
            return CallResult(status="error", reason=f"{type(e).__name__}: {str(e)[:300]}")
        u = msg.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
        on_fact(Fact(kind="usage", data=usage.model_dump()))
        if msg.stop_reason == "refusal":
            det = getattr(msg, "stop_details", None)
            return CallResult(
                status="no_output",
                reason=f"refusal: {getattr(det, 'category', None)} {getattr(det, 'explanation', '') or ''}".strip(),
                usage=usage,
                model_used=msg.model,
            )
        if msg.stop_reason == "max_tokens":
            return CallResult(
                status="no_output",
                reason=f"max_tokens ({call.max_tokens}) reached before the answer closed",
                usage=usage,
                model_used=msg.model,
            )
        text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            return CallResult(
                status="no_output", reason="no text block in the answer", usage=usage, model_used=msg.model
            )
        try:
            parsed = json.loads(text)
        except ValueError as e:
            return CallResult(
                status="no_output",
                raw_text=text,
                reason=f"the answer is not JSON: {e}",
                usage=usage,
                model_used=msg.model,
            )
        on_fact(Fact(kind="final", text="json"))
        return CallResult(status="final", raw_text=text, parsed=parsed, usage=usage, model_used=msg.model)
