"""The fake backend: a schema-valid answer with no model (rule 12).

Answer sources, in order: a fixture file named by the call (`call.fixture`), a faker registered
for the schema name, else a generic instance built from the wire schema and the fields'
examples. `FAKE_REFUSE` makes the answer schema-invalid for n attempts so the re-ask loop is
walked; `same` makes every attempt identical so the no-progress stop is walked.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from . import knobs
from .base import CallResult, CallSpec, Capabilities, Fact, SchemaMode, Usage

Faker = Callable[[CallSpec], dict[str, Any]]
_FAKERS: dict[str, Faker] = {}


def register_faker(schema_name: str, fn: Faker) -> None:
    _FAKERS[schema_name] = fn


def generic_instance(schema: dict[str, Any], defs: dict[str, Any] | None = None, *, list_len: int = 1) -> Any:
    defs = defs if defs is not None else schema.get("$defs", {})
    node = schema
    if "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[-1]]
    if "examples" in node and node["examples"]:
        return node["examples"][0]
    if "enum" in node:
        return node["enum"][0]
    if "const" in node:
        return node["const"]
    if "anyOf" in node:
        opts = [o for o in node["anyOf"] if o.get("type") != "null"]
        return generic_instance(opts[0], defs, list_len=list_len) if opts else None
    t = node.get("type")
    if t == "object":
        return {
            k: generic_instance(v, defs, list_len=list_len) for k, v in node.get("properties", {}).items()
        }
    if t == "array":
        return [generic_instance(node.get("items", {}), defs, list_len=list_len) for _ in range(list_len)]
    if t == "string":
        d = node.get("description", "text")
        return f"fake {d} " + "x" * 48  # long enough for any min_length a validator keeps
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    return None


class FakeBackend:
    name = "fake"

    def __init__(self, fixtures_root: Path | None = None, fakers: dict[str, Faker] | None = None) -> None:
        self.fixtures_root = fixtures_root
        self.fakers = dict(fakers or {})  # a recipe binds these to the run (they may read the store)
        self._attempts: dict[tuple[str, str], int] = {}

    def capabilities(self) -> Capabilities:
        return Capabilities(schema_mode=SchemaMode.GRAMMAR, tools_denyable=True, streams=True)

    def _answer(self, call: CallSpec) -> dict[str, Any]:
        if call.fixture and self.fixtures_root is not None:
            p = self.fixtures_root / f"{call.fixture}.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        if call.schema_name in self.fakers:
            return self.fakers[call.schema_name](call)
        if call.schema_name in _FAKERS:
            return _FAKERS[call.schema_name](call)
        # the wire schema has examples stripped; fakers and fixtures carry the shape's intent
        return generic_instance(call.schema_)

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult:
        # FAKE_SLEEP: a walk knob so that two parallel steps overlap measurably (phase 5)
        import os as _os
        import time as _time

        _pause = float(_os.environ.get("FAKE_SLEEP", "0") or 0)
        if _pause > 0:
            _time.sleep(_pause)
        key = (call.role, call.schema_name)
        n = self._attempts.get(key, 0) + 1
        self._attempts[key] = n
        if knobs.role_flag("FAKE_STALL") == call.role:
            time.sleep(call.stall_seconds + 1)
            return CallResult(
                status="stall",
                reason=f"fake: no fact for {call.stall_seconds}s",
                usage=Usage(input_tokens=10),
            )
        if knobs.role_flag("FAKE_TOOLLESS_VIOLATION") == call.role and not call.tools:
            on_fact(Fact(kind="tool", text="fake attempted a tool call on a tool-less step"))
            return CallResult(
                status="error", reason="tool call on a tool-less step", usage=Usage(input_tokens=10)
            )
        on_fact(Fact(kind="turn", text="fake turn 1"))
        answer = self._answer(call)
        r = knobs.refuse()
        if r and r.role == call.role and (r.count is None or call.attempt <= r.count):
            # schema-invalid on purpose. A finite count varies the problem per attempt (the loop must
            # see progress); `same` repeats it exactly (the no-progress stop must fire).
            broken = dict(answer)
            req = call.schema_.get("required", [])
            i = 0 if r.count is None else (call.attempt - 1) % max(len(req), 1)
            if req:
                broken.pop(req[i], None)
            broken["__fake_extra__" if r.count is None else f"__fake_extra_{call.attempt}__"] = (
                "refused by knob"
            )
            answer = broken
        usage = Usage(input_tokens=len(call.user) // 4, output_tokens=len(json.dumps(answer)) // 4)
        on_fact(Fact(kind="usage", data=usage.model_dump()))
        on_fact(Fact(kind="final", text="fake final"))
        return CallResult(
            status="final", raw_text=json.dumps(answer), parsed=answer, usage=usage, model_used=call.model
        )
