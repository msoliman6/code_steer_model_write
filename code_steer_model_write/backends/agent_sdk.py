"""The Claude Agent SDK backend: `output_format` json_schema, validated at the tool boundary
(fail-closed), every tool and setting source denied (rule 2)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from .base import CallResult, CallSpec, Capabilities, Fact, SchemaMode, Usage
from .cli import CLAUDE_ALL_TOOLS


class AgentSdkBackend:
    name = "agent_sdk"

    def capabilities(self) -> Capabilities:
        return Capabilities(schema_mode=SchemaMode.TOOL_BOUNDARY, tools_denyable=True, streams=True)

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult:
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                SystemMessage,
                query,
            )
        except ImportError:
            return CallResult(
                status="error",
                reason="claude-agent-sdk is not installed (pip install claude-agent-sdk) -- or use the claude_cli backend",
            )
        if call.tools:
            return CallResult(status="error", reason="the agent_sdk backend runs tool-less steps only in v1")
        options = ClaudeAgentOptions(
            output_format={"type": "json_schema", "schema": call.schema_},
            allowed_tools=[],
            disallowed_tools=list(CLAUDE_ALL_TOOLS),
            mcp_servers={},
            setting_sources=[],
            max_turns=call.max_turns,
            model=call.model,
            system_prompt=call.system,
        )
        result: dict[str, Any] = {}

        async def run() -> None:
            async for message in query(prompt=call.user, options=options):
                if isinstance(message, SystemMessage):
                    on_fact(Fact(kind="note", text="init", data={"subtype": getattr(message, "subtype", "")}))
                elif isinstance(message, AssistantMessage):
                    for block in getattr(message, "content", []) or []:
                        bt = type(block).__name__
                        if bt == "ToolUseBlock":
                            on_fact(
                                Fact(
                                    kind="tool",
                                    text=getattr(block, "name", ""),
                                    data={"tool": getattr(block, "name", "")},
                                )
                            )
                        elif bt == "ThinkingBlock":
                            on_fact(Fact(kind="thinking", text=(getattr(block, "thinking", "") or "")[:120]))
                        else:
                            on_fact(Fact(kind="turn", text=bt))
                elif isinstance(message, ResultMessage):
                    result["subtype"] = message.subtype
                    result["structured_output"] = getattr(message, "structured_output", None)
                    u = getattr(message, "usage", None) or {}
                    result["usage"] = Usage(
                        input_tokens=int(u.get("input_tokens", 0)),
                        output_tokens=int(u.get("output_tokens", 0)),
                        cache_read_tokens=int(u.get("cache_read_input_tokens", 0)),
                        turns=int(getattr(message, "num_turns", 1) or 1),
                    )
                    on_fact(Fact(kind="usage", data=result["usage"].model_dump()))

        try:
            asyncio.run(run())
        except Exception as e:  # noqa: BLE001
            return CallResult(
                status="error",
                reason=f"{type(e).__name__}: {str(e)[:300]}",
                usage=result.get("usage", Usage()),
            )
        usage = result.get("usage", Usage())
        if result.get("subtype") == "success" and result.get("structured_output") is not None:
            so = result["structured_output"]
            on_fact(Fact(kind="final", text="structured output"))
            return CallResult(
                status="final", raw_text=json.dumps(so), parsed=so, usage=usage, model_used=call.model
            )
        return CallResult(
            status="no_output",
            reason=f"agent sdk: {result.get('subtype') or 'no result message'} without structured output",
            usage=usage,
        )
