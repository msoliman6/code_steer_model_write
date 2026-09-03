"""The contract: the one artifact everything downstream cites (rules 3, 5).

The model chooses a `key` per clause (a slug unique in the contract) and cross-references by
key; code assigns the `C-`/`A-` id on ingest and keeps it across re-emits by key (ids never
renumbered: a key that disappears retires its id). Two views: the full contract (the
implementer's) and the test-visible view without the algorithm (the test author's); the
freeze hashes both.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from ..ids import Prefix, next_id
from ..spec.base import Artifact, CheckContext, Problem

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
BANNED_CLAUSE_WORDS = ["correctly", "properly", "as expected", "gracefully", "appropriately", "etc"]
BANNED_CLAUSE_OPENERS = ("verify", "test", "confirm", "check", "ensure")


class Clause(Artifact):
    id: SkipJsonSchema[str | None] = None
    key: str = Field(description="a slug unique in this contract; other clauses refer to it")


class Term(Clause):
    term: str
    definition: str = Field(min_length=6)


class Param(Artifact):
    name: str
    type: str = Field(description="a Python type expression, e.g. `str`, `int | None`, `list[str]`")
    default: str | None = Field(default=None, description="the default as source text, or null")


class Field_(Clause):
    name: str
    type: str
    tags: list[str] = Field(default_factory=list)


class Unit(Clause):
    name: str = Field(description="the callable's name")
    kind: Literal["function", "class", "method"] = "function"
    params: list[Param]
    returns: str = Field(description="the return type expression")
    holds: str = Field(min_length=10, description="what is true of the return, in one sentence")


class Constant(Clause):
    name: str
    value: str = Field(description="as source text")
    tag: str = Field(default="", description="tolerance | limit | format | other")


class Invariant(Clause):
    claim: str = Field(min_length=10, description="a claim a test can falsify")
    measurement: str = Field(default="", description="how it is observed; empty means exact")


class Negative(Clause):
    must_not: str = Field(min_length=6)


class FailurePolicy(Clause):
    on: str = Field(description="the condition")
    policy: str = Field(description="what happens: raise X, return Y, log and continue")
    observable: str = Field(description="how a test sees it")


class Tolerance(Clause):
    clause: str = Field(description="the key of the clause this tolerance qualifies")
    kind: str = Field(description="absolute | relative | count | duration")
    value: str = Field(default="UNDECIDED", description="a number, or UNDECIDED (asked at the risk gate)")


class Step(Artifact):
    id: SkipJsonSchema[str | None] = None
    key: str
    text: str = Field(min_length=6)
    implements: list[str] = Field(description="the keys of the clauses this step implements")
    uses: list[str] = Field(default_factory=list, description="constant keys it reads")


class Algorithm(Artifact):
    unit: str = Field(description="the unit's key")
    steps: list[Step]


class Contract(Artifact):
    block: str
    vocabulary: list[Term] = Field(default_factory=list)
    input: list[Field_]
    output: list[Field_]
    units: list[Unit] = Field(min_length=1)
    constants: list[Constant] = Field(default_factory=list)
    invariants: list[Invariant] = Field(min_length=1)
    negative: list[Negative] = Field(default_factory=list)
    failure: list[FailurePolicy] = Field(default_factory=list)
    tolerances: list[Tolerance] = Field(default_factory=list)
    algorithm: list[Algorithm] = Field(description="per unit, the steps; stripped from the test-visible view")
    version: SkipJsonSchema[int] = 0
    retired: SkipJsonSchema[list[str]] = []

    # ---- clauses as one sequence ---------------------------------------------------------

    def clauses(self) -> list[Clause]:
        return [
            *self.vocabulary,
            *self.input,
            *self.output,
            *self.units,
            *self.constants,
            *self.invariants,
            *self.negative,
            *self.failure,
            *self.tolerances,
        ]

    def steps(self) -> list[Step]:
        return [s for a in self.algorithm for s in a.steps]

    def key_to_id(self) -> dict[str, str]:
        m = {c.key: c.id for c in self.clauses() if c.id}
        m.update({s.key: s.id for s in self.steps() if s.id})
        return m

    def ids(self) -> list[str]:
        return [i for i in self.key_to_id().values()]

    # ---- semantic checks (rule 7) ----------------------------------------------------------

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        keys = [c.key for c in self.clauses()]
        skeys = [s.key for s in self.steps()]
        for k in keys + skeys:
            if not KEY_RE.match(k):
                out.append(Problem(code="key_invalid", message=f"key {k!r} must match {KEY_RE.pattern}"))
        dups = sorted({k for k in keys + skeys if (keys + skeys).count(k) > 1})
        if dups:
            out.append(Problem(code="key_dup", message=f"keys must be unique in the contract: {dups}"))
        kset = set(keys)
        ukeys = {u.key for u in self.units}
        ckeys = {c.key for c in self.constants}
        for a in self.algorithm:
            if a.unit not in ukeys:
                out.append(
                    Problem(
                        code="algorithm_unit_unknown",
                        message=f"algorithm for {a.unit!r}: no unit has that key",
                    )
                )
            for s in a.steps:
                for k in s.implements:
                    if k not in kset:
                        out.append(
                            Problem(
                                code="implements_unresolved",
                                message=f"step {s.key}: implements {k!r}, not a clause key",
                            )
                        )
                for k in s.uses:
                    if k not in ckeys:
                        out.append(
                            Problem(
                                code="uses_unresolved",
                                message=f"step {s.key}: uses {k!r}, not a constant key",
                            )
                        )
        for u in self.units:
            if u.key not in {a.unit for a in self.algorithm}:
                out.append(
                    Problem(code="unit_without_algorithm", message=f"unit {u.key!r} has no algorithm steps")
                )
        for t in self.tolerances:
            if t.clause not in kset:
                out.append(
                    Problem(
                        code="tolerance_clause_unknown",
                        message=f"tolerance {t.key}: clause {t.clause!r} is not a key",
                    )
                )
        for c in self.invariants + self.negative:
            text = getattr(c, "claim", None) or getattr(c, "must_not", "")
            low = text.lower().strip()
            if low.split(" ", 1)[0].rstrip(":") in BANNED_CLAUSE_OPENERS:
                out.append(
                    Problem(
                        code="clause_is_a_test",
                        message=f"{c.key}: a clause never opens with Verify/Test/Confirm/Check/Ensure",
                    )
                )
            for w in BANNED_CLAUSE_WORDS:
                if re.search(r"\b" + re.escape(w) + r"\b", low):
                    out.append(
                        Problem(
                            code="banned_word",
                            message=f"{c.key}: '{w}' is satisfied by any implementer who thinks it is",
                        )
                    )
        return out

    # ---- ids (rule 5): assigned by code, kept by key across versions -----------------------

    def with_ids(self, previous: "Contract | None") -> "Contract":
        prev_map = previous.key_to_id() if previous else {}
        taken = list(prev_map.values()) + (previous.retired if previous else [])
        c = self.model_copy(deep=True)
        for cl in c.clauses():
            cl.id = prev_map.get(cl.key) or next_id(Prefix.CLAUSE, taken)
            taken.append(cl.id)
        for s in c.steps():
            s.id = prev_map.get(s.key) or next_id(Prefix.STEP, taken)
            taken.append(s.id)
        now = set(c.key_to_id().values())
        c.retired = sorted((set(prev_map.values()) | set(previous.retired if previous else [])) - now)
        c.version = (previous.version if previous else 0) + 1
        return c

    # ---- views and the freeze --------------------------------------------------------------

    def test_visible(self) -> "Contract":
        return self.model_copy(update={"algorithm": []}, deep=True)

    def sha(self) -> str:
        canon = json.dumps(
            self.model_dump(mode="json", exclude={"version", "retired"}),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canon.encode()).hexdigest()

    def render_md(self, audience: str = "model", drop: set[str] | None = None) -> str | None:
        drop = drop or set()
        L: list[str] = [f"## Contract: {self.block}" + (f" (v{self.version})" if self.version else ""), ""]

        def tab(title: str, rows: list[Clause], cols: list[str]) -> None:
            if not rows:
                return
            L.append(f"### {title}")
            L.append("")
            L.append("| id | key | " + " | ".join(cols) + " |")
            L.append("|---|---|" + "---|" * len(cols))
            for r in rows:
                vals = []
                for c in cols:
                    v = getattr(r, c)
                    if isinstance(v, list):
                        v = ", ".join(
                            x
                            if isinstance(x, str)
                            else f"{x.name}: {x.type}"
                            + (f" = {x.default}" if getattr(x, 'default', None) else "")
                            for x in v
                        )
                    vals.append(str(v).replace("|", "\\|"))
                L.append(f"| {r.id or ''} | {r.key} | " + " | ".join(vals) + " |")
            L.append("")

        tab("1. Vocabulary", self.vocabulary, ["term", "definition"])
        tab("2.1 Input", self.input, ["name", "type", "tags"])
        tab("2.2 Output", self.output, ["name", "type", "tags"])
        tab("2.3 Units", self.units, ["name", "kind", "params", "returns", "holds"])
        tab("3. Constants", self.constants, ["name", "value", "tag"])
        tab("4. Invariants", self.invariants, ["claim", "measurement"])
        tab("5. Negative scope", self.negative, ["must_not"])
        tab("6. Failure policy", self.failure, ["on", "policy", "observable"])
        tab("7. Tolerances", self.tolerances, ["clause", "kind", "value"])
        if "algorithm" not in drop and self.algorithm:
            L.append("### 8. Algorithm")
            L.append("")
            for a in self.algorithm:
                L.append(f"**{a.unit}**")
                L.append("")
                for s in a.steps:
                    L.append(
                        f"- {s.id or ''} `{s.key}`: {s.text} -> implements {', '.join(s.implements)}"
                        + (f"; uses {', '.join(s.uses)}" if s.uses else "")
                    )
                L.append("")
        if self.retired:
            L.append("### 10. Retired")
            L.append("")
            L.append(", ".join(self.retired))
            L.append("")
        return "\n".join(L)
