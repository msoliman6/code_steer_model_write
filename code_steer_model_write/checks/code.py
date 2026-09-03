"""Code checks -- the bottom rung of the ladder (rule 7): cheap, deterministic, first.

Each returns a list of Problems; empty means pass. They read records (the artifact, the known
ids), never patterns in text.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from ..ids import find_ids
from ..spec.base import Artifact, CheckContext, Problem


def cites_resolve(answer: Artifact, ctx: CheckContext) -> list[Problem]:
    return [
        Problem(code="cite_unresolved", message=f"{c} is not a known id")
        for c in answer.cited_ids()
        if c not in ctx.known_ids
    ]


def no_minted_ids(answer: Artifact, ctx: CheckContext) -> list[Problem]:
    """A model may cite ids; it never invents one (rule 5). Any id in the answer's text that is
    not known is a minted id."""
    text = answer.model_dump_json()
    return [
        Problem(code="id_minted", message=f"{i} does not exist; code assigns ids")
        for i in find_ids(text)
        if i not in ctx.known_ids
    ]


def banned_words(
    words: Iterable[str], *, fields: Iterable[str] | None = None
) -> Callable[[Artifact, CheckContext], list[Problem]]:
    """The greppable list a contract or claim must not use: 'handles errors gracefully',
    'appropriately', 'etc.' -- words that make a clause unfalsifiable."""
    pats = [(w, re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)) for w in words]
    fset = set(fields) if fields else None

    def check(answer: Artifact, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        for path, value in _walk_strings(answer.model_dump()):
            if fset and path.split(".")[-1].split("[")[0] not in fset:
                continue
            for w, pat in pats:
                if pat.search(value):
                    out.append(
                        Problem(
                            code="banned_word",
                            path=path,
                            message=f"'{w}' makes this unfalsifiable; say what is observed",
                        )
                    )
        return out

    return check


def min_words(field: str, n: int) -> Callable[[Artifact, CheckContext], list[Problem]]:
    def check(answer: Artifact, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        for path, value in _walk_strings(answer.model_dump()):
            if path.split(".")[-1] == field and len(value.split()) < n:
                out.append(
                    Problem(code="too_short", path=path, message=f"{field} needs {n}+ words of reasoning")
                )
        return out

    return check


def set_difference(expected: set[str], got: set[str], *, what: str) -> list[Problem]:
    """Coverage as arithmetic (rule 5): what was required minus what was covered, and the
    reverse. Used by the envelope check, the coverage check, the manifest check."""
    out: list[Problem] = []
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    if missing:
        out.append(Problem(code=f"{what}_missing", message=f"{what} not covered: {missing}"))
    if extra:
        out.append(Problem(code=f"{what}_extra", message=f"{what} not asked for: {extra}"))
    return out


def empty_set(items: Iterable[Any]) -> bool:
    """The generator's question before issuing a step built for one-or-more (rule 9)."""
    return not any(True for _ in items)


def _walk_strings(node: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{path}[{i}]")
