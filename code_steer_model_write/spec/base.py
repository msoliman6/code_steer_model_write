"""The pydantic class is the one owner of every model-output shape (rules 2, 4, 5).

From one `Artifact` subclass derive, and never hand-write:
  - `wire_schema()`  the strict JSON schema a backend enforces at generation
  - `template()`     the empty skeleton pasted into the prompt
  - `guide()`        the field table pasted into the prompt
  - `model_validate` the validator (always run, even on grammar backends)
  - `render_md()`    the markdown view the *next* model or the human reads (artifacts/render.py)
  - `semantic_problems()` the checks a schema cannot say (cites resolve, set differences)

Ids are `SkipJsonSchema` fields: the model never sees or mints them; code assigns on ingest.
"""

from __future__ import annotations

import copy
import json
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class Problem(BaseModel):
    """One reason an answer is refused. `code` is stable and greppable; `message` is the
    reason in words, carried verbatim into the re-ask (rule 6)."""

    code: str
    message: str
    path: str | None = None

    def __str__(self) -> str:
        return f"{self.code}{' at ' + self.path if self.path else ''}: {self.message}"


class CheckContext(BaseModel):
    """What a semantic check may consult: the ids that exist, the artifacts on disk, the step.
    Kept small on purpose -- a check reads records, never patterns (ledger class)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    known_ids: set[str] = Field(default_factory=set)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    step: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


# Keywords a grammar backend either rejects or applies inconsistently. They stay in the
# pydantic validators (rule 4: one owner) and leave the wire schema.
_STRIPPED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "default",
    "examples",
    "title",
    "deprecated",
    "readOnly",
    "writeOnly",
}


def _strict(node: Any) -> Any:
    """Post-pass over a JSON schema: every object closed and fully required, the keywords a
    grammar cannot hold removed, `$defs` kept."""
    if isinstance(node, list):
        return [_strict(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in _STRIPPED:
            continue
        if k == "description":
            out[k] = v
            continue
        out[k] = _strict(v)
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"].keys())
        out["additionalProperties"] = False
    return out


class Artifact(BaseModel):
    """Base of every model-output shape."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    #: The name the backend sees (`schema_name`); defaults to the class name.
    schema_title: ClassVar[str | None] = None

    # ---- derived views (rule 4) ----------------------------------------------------------

    @classmethod
    def wire_schema(cls) -> dict[str, Any]:
        raw = cls.model_json_schema(mode="serialization")
        s = _strict(copy.deepcopy(raw))
        s["title"] = cls.schema_title or cls.__name__
        return s

    @classmethod
    def schema_name(cls) -> str:
        return cls.schema_title or cls.__name__

    @classmethod
    def template(cls) -> str:
        """An empty skeleton of the answer, one line per leaf, as the model must return it."""
        schema = cls.wire_schema()
        return json.dumps(_skeleton(schema, schema.get("$defs", {}), depth=0), indent=2, ensure_ascii=False)

    @classmethod
    def guide(cls) -> str:
        """A markdown table: path, type, what goes there, an example when the field has one."""
        raw = cls.model_json_schema(mode="serialization")
        rows: list[tuple[str, str, str, str]] = []
        _guide_rows(raw, raw.get("$defs", {}), "", rows, seen=set())
        lines = ["| field | type | what goes there | example |", "|---|---|---|---|"]
        for path, typ, desc, ex in rows:
            lines.append(f"| `{path}` | {typ} | {desc} | {ex} |")
        return "\n".join(lines)

    # ---- the markdown view (rule 2) ------------------------------------------------------

    def render_md(self, audience: str = "model", drop: set[str] | None = None) -> str | None:
        """Override to shape the view; return None to use the generic renderer
        (artifacts/render.py). `drop` names top-level fields a role must not see."""
        return None

    # ---- checks a schema cannot say (rule 7) ---------------------------------------------

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        return []

    # ---- ids (rule 5) --------------------------------------------------------------------

    def cited_ids(self) -> list[str]:
        """Every id this artifact cites, from every `cites` field at any depth."""
        out: list[str] = []
        _collect_cites(self.model_dump(), out)
        return out


def _collect_cites(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("cites", "implements", "covers") and isinstance(v, list):
                for s in v:
                    if isinstance(s, str) and s not in out:
                        out.append(s)
            else:
                _collect_cites(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_cites(v, out)


def problems_of(items: list[Problem]) -> str:
    return "\n".join(f"- {p}" for p in items)


# ---- schema walkers ----------------------------------------------------------------------


def _deref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return defs[name]
    return node


def _skeleton(node: dict[str, Any], defs: dict[str, Any], depth: int) -> Any:
    node = _deref(node, defs)
    if "enum" in node:
        return "<one of: " + " | ".join(str(e) for e in node["enum"]) + ">"
    if "const" in node:
        return node["const"]
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if _deref(o, defs).get("type") != "null"]
        return _skeleton(options[0], defs, depth) if options else None
    t = node.get("type")
    if t == "object":
        return {k: _skeleton(v, defs, depth + 1) for k, v in node.get("properties", {}).items()}
    if t == "array":
        return [_skeleton(node.get("items", {}), defs, depth + 1)]
    if t == "string":
        d = node.get("description")
        return f"<{d}>" if d else "<text>"
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    return None


def _typename(node: dict[str, Any], defs: dict[str, Any]) -> str:
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]
    if "enum" in node:
        return " \\| ".join(str(e) for e in node["enum"])
    if "anyOf" in node:
        return " \\| ".join(_typename(o, defs) for o in node["anyOf"])
    t = node.get("type", "any")
    if t == "array":
        return f"list of {_typename(node.get('items', {}), defs)}"
    return str(t)


def _guide_rows(
    node: dict[str, Any],
    defs: dict[str, Any],
    prefix: str,
    rows: list[tuple[str, str, str, str]],
    seen: set[str],
) -> None:
    node = _deref(node, defs)
    if node.get("type") == "object":
        for k, v in node.get("properties", {}).items():
            path = f"{prefix}.{k}" if prefix else k
            vv = _deref(v, defs)
            ex = ""
            if "examples" in v and v["examples"]:
                ex = "`" + json.dumps(v["examples"][0], ensure_ascii=False) + "`"
            elif "examples" in vv and vv["examples"]:
                ex = "`" + json.dumps(vv["examples"][0], ensure_ascii=False) + "`"
            rows.append((path, _typename(v, defs), v.get("description", vv.get("description", "")), ex))
            target = vv
            if target.get("type") == "array":
                target = _deref(target.get("items", {}), defs)
                path = path + "[]"
            if "anyOf" in target:
                opts = [_deref(o, defs) for o in target["anyOf"] if _deref(o, defs).get("type") != "null"]
                target = opts[0] if opts else {}
            if target.get("type") == "object" and "properties" in target:
                key = json.dumps(target, sort_keys=True)[:200] + path
                if key in seen:
                    continue
                seen.add(key)
                _guide_rows(target, defs, path, rows, seen)
