"""The backend protocol: one call in, one answer out, facts streamed in between (rules 2, 10).

A backend never decides anything: it delivers the schema to the vendor, denies tools, streams
facts, and reports honestly (`status` is never `final` without an answer; `reason` is never
empty otherwise).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field

from ..spec.events import now


class SchemaMode(StrEnum):
    GRAMMAR = "grammar"  # the sampler is constrained (Anthropic structured output, codex --output-schema)
    TOOL_BOUNDARY = "tool_boundary"  # validated at the tool boundary and refused (Agent SDK, claude -p)
    VALIDATE_ONLY = "validate_only"  # the vendor may ignore the schema; we validate (LiteLLM)


class Capabilities(BaseModel):
    schema_mode: SchemaMode
    tools_denyable: bool = True
    streams: bool = False
    threads: bool = False


class ToolDef(BaseModel):
    """A typed code function a tool-bearing step may expose (rule 2: only when needed)."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Any]


class Fact(BaseModel):
    """One normalised thing the stream said: a turn, a tool call, a write, usage, the final
    answer, an error, a heartbeat. Facts are the liveness signal; exit is the backstop."""

    kind: Literal["turn", "tool", "write", "usage", "thinking", "final", "error", "heartbeat", "note"]
    ts: datetime = Field(default_factory=now)
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    turns: int = 1
    tool_calls: int = 0

    def __add__(self, o: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + o.input_tokens,
            output_tokens=self.output_tokens + o.output_tokens,
            cache_read_tokens=self.cache_read_tokens + o.cache_read_tokens,
            turns=self.turns + o.turns,
            tool_calls=self.tool_calls + o.tool_calls,
        )

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class CallSpec(BaseModel):
    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

    role: str
    model: str
    effort: str = "medium"
    thinking: bool = False
    system: str
    user: str
    schema_: dict[str, Any] = Field(alias="schema")
    schema_name: str
    tools: list[ToolDef] = Field(default_factory=list)
    max_turns: int = 3
    max_tokens: int = 16000
    stream_path: Path | None = None
    attempt: int = 1
    stall_seconds: int = 180
    scope_root: Path | None = None  # a tool-bearing call may write only under this folder
    fixture: str | None = None  # the fake backend's hint: which fixture answers this call
    schema_model: Any = None  # the Artifact class itself, for a backend that takes a type (pydantic_ai)


class CallResult(BaseModel):
    status: Literal["final", "no_output", "error", "stall", "scope", "budget"]
    raw_text: str | None = None
    parsed: dict[str, Any] | None = None
    usage: Usage = Field(default_factory=Usage)
    model_used: str | None = None
    facts: list[Fact] = Field(default_factory=list)  # the last few, for a halt report
    reason: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.status != "final" and not self.reason:
            raise ValueError(
                f"a {self.status} result must carry a reason (ledger: a message that hides the reason)"
            )
        if self.status == "final" and self.parsed is None:
            raise ValueError("a final result must carry the parsed answer")


class Backend(Protocol):
    name: str

    def capabilities(self) -> Capabilities: ...

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult: ...
