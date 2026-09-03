"""Id namespaces -- the joints between every JSON file (rule 5).

Decided once, globally: a prefix per kind, four digits, assigned by code on ingest, never by a
model, never renumbered. A model may *cite* ids; it never *mints* one.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Iterable


class Prefix(StrEnum):
    CLAUSE = "C"  # a contract clause
    STEP = "A"  # an algorithm step
    PROPERTY = "P"  # a verification property
    FINDING = "F"  # a review finding
    QUESTION = "Q"  # a question put to a human (or auto-answered)
    DECISION = "D"  # a recorded decision
    RUN_STEP = "S"  # a driver step
    VERSION = "V"  # an artifact version
    RULING = "R"  # a triage ruling
    TASK = "T"  # a build task row
    ASSUMPTION = "L"  # an assumptions-ledger row
    GAP = "G"  # a contract gap raised by the verification author


ID_RE = re.compile(r"^([A-Z])-(\d{4})$")
ANY_ID_RE = re.compile(r"\b([A-Z])-(\d{4})\b")


def is_id(s: str) -> bool:
    return bool(ID_RE.match(s))


def prefix_of(s: str) -> Prefix:
    m = ID_RE.match(s)
    if not m:
        raise ValueError(f"not an id: {s!r}")
    return Prefix(m.group(1))


def number_of(s: str) -> int:
    m = ID_RE.match(s)
    if not m:
        raise ValueError(f"not an id: {s!r}")
    return int(m.group(2))


def fmt(prefix: Prefix, n: int) -> str:
    if not 1 <= n <= 9999:
        raise ValueError(f"id number out of range: {n}")
    return f"{prefix.value}-{n:04d}"


def next_id(prefix: Prefix, taken: Iterable[str]) -> str:
    """The next unused id in the namespace. Ids are never reused: the maximum taken + 1."""
    nums = [number_of(t) for t in taken if is_id(t) and prefix_of(t) == prefix]
    return fmt(prefix, (max(nums) + 1) if nums else 1)


def assign(prefix: Prefix, count: int, taken: Iterable[str]) -> list[str]:
    """`count` fresh ids after everything already taken, in order."""
    out: list[str] = []
    seen = list(taken)
    for _ in range(count):
        nid = next_id(prefix, seen)
        out.append(nid)
        seen.append(nid)
    return out


def find_ids(text: str) -> list[str]:
    """Every id mentioned in a text, in order, without duplicates."""
    seen: list[str] = []
    for m in ANY_ID_RE.finditer(text):
        s = f"{m.group(1)}-{m.group(2)}"
        if s not in seen:
            seen.append(s)
    return seen
