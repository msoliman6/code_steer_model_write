"""The code-builder's fake answers (rule 12): schema-valid, bound to the run's store so a
re-emit is the real current artifact, and real enough that the offline walk runs pytest on
the fake-written code. Knobs: FAKE_FINDINGS, FAKE_CLOSING, FAKE_VERDICT (backends/knobs.py) and
FAKE_IMPL=buggy (the source fails one property, walking the triage path)."""

from __future__ import annotations

import os
import re
from typing import Any, Callable

from ...artifacts.contract import Contract
from ...artifacts.plan import Plan
from ...artifacts.store import Store
from ...artifacts.vspec import VerificationSpec
from ...backends import knobs
from ...ids import find_ids
from ...state.run import RunPaths

SLUG_CONTRACT: dict[str, Any] = {
    "block": "slug",
    "vocabulary": [
        {
            "key": "slug_term",
            "term": "slug",
            "definition": "lowercase ascii letters and digits, words joined by single hyphens, no leading or trailing hyphen",
        }
    ],
    "input": [{"key": "in_text", "name": "text", "type": "str", "tags": []}],
    "output": [{"key": "out_slug", "name": "slug", "type": "str", "tags": []}],
    "units": [
        {
            "key": "slugify",
            "name": "slugify",
            "kind": "function",
            "params": [{"name": "text", "type": "str", "default": None}],
            "returns": "str",
            "holds": "returns the slug of text as defined in the vocabulary",
        }
    ],
    "constants": [{"key": "max_len", "name": "MAX_LEN", "value": "80", "tag": "limit"}],
    "invariants": [
        {
            "key": "inv_charset",
            "claim": "every character of the result is one of a-z, 0-9 or '-'",
            "measurement": "",
        },
        {
            "key": "inv_words",
            "claim": "every maximal run of ascii letters or digits in the input appears, lowercased, as one word of the result, in order",
            "measurement": "",
        },
        {"key": "inv_len", "claim": "the result has at most MAX_LEN characters", "measurement": ""},
    ],
    "negative": [{"key": "neg_unicode", "must_not": "transliterate non-ascii letters; they are separators"}],
    "failure": [
        {
            "key": "fail_none",
            "on": "text is None",
            "policy": "raise TypeError",
            "observable": "the exception type",
        }
    ],
    "tolerances": [],
    "algorithm": [
        {
            "unit": "slugify",
            "steps": [
                {
                    "key": "s_none",
                    "text": "raise TypeError when text is None",
                    "implements": ["fail_none"],
                    "uses": [],
                },
                {
                    "key": "s_lower",
                    "text": "lowercase the text",
                    "implements": ["inv_charset", "inv_words"],
                    "uses": [],
                },
                {
                    "key": "s_join",
                    "text": "replace every run of characters outside a-z0-9 with one hyphen, strip hyphens at both ends, cut at MAX_LEN",
                    "implements": ["inv_charset", "inv_words", "inv_len"],
                    "uses": ["max_len"],
                },
            ],
        }
    ],
}

IMPL_OK = '''"""slug: the one block."""

from __future__ import annotations

import re

MAX_LEN = 80  # C-constant max_len


def slugify(text: str) -> str:
    # {S_NONE}: raise TypeError when text is None
    if text is None:
        raise TypeError("text must be a str, not None")
    # {S_LOWER}: lowercase
    lowered = text.lower()
    # {S_JOIN}: runs outside a-z0-9 become one hyphen, trimmed, cut at MAX_LEN
    joined = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return joined[:MAX_LEN].rstrip("-")
'''

IMPL_BUGGY = IMPL_OK.replace("lowered = text.lower()", "lowered = text  # BUG: not lowercased")

TESTS = '''"""Tests for slug, written from the test-visible contract alone."""

import pytest

from {MODULE} import slugify


def test_{P1}_charset():
    # falsifies: a character outside a-z0-9- appears in the result
    out = slugify("Hello, World! 2026")
    assert out and set(out) <= set("abcdefghijklmnopqrstuvwxyz0123456789-")


def test_{P2}_words_survive_in_order():
    # falsifies: an input word is missing, reordered or not lowercased
    assert slugify("Hello World Again") == "hello-world-again"
    assert slugify("  A  b--C ") == "a-b-c"


def test_{P3}_none_raises():
    # falsifies: no TypeError on None
    with pytest.raises(TypeError):
        slugify(None)


def test_{P4}_length_cap():
    # falsifies: a result longer than MAX_LEN, or a cut that loses the input's leading characters
    out = slugify("x" * 200)
    assert len(out) == 80 and out == "x" * 80


def test_{P5}_non_ascii_is_a_separator():
    # falsifies: the non-ascii letter is transliterated instead of splitting the word
    assert slugify("caf\u00e9 au lait") == "caf-au-lait"
'''


def _ids_of_kind(text: str, prefix: str) -> list[str]:
    return [i for i in find_ids(text) if i.startswith(prefix + "-")]


def fakers(paths: RunPaths, store: Store) -> dict[str, Callable[[Any], dict[str, Any]]]:
    def ledger(call):
        return {
            "rows": [
                {
                    "assumption": "the slug is for URLs: ascii only, hyphen-separated",
                    "basis": "the brief's request",
                    "if_wrong": "unicode words vanish",
                    "confirm": "unknown",
                },
                {
                    "assumption": "one module, one public function",
                    "basis": "the brief's surface",
                    "if_wrong": "the plan needs a second block",
                    "confirm": "unknown",
                },
            ],
            "queue": [],
        }

    def plan(call):
        return {
            "blocks": [
                {
                    "name": "slug",
                    "boundary": "turns any string into a URL slug; nothing else",
                    "inputs": ["text: str"],
                    "outputs": ["slug: str"],
                    "writes": ["src/slug.py"],
                    "shape_driver": "one function, one file",
                }
            ],
            "decomposition": "one block because the brief names one surface and one function",
            "constants": ["MAX_LEN"],
            "order": ["slug"],
            "rejected": [{"idea": "transliteration", "why": "dead on the method: out of scope"}],
            "risks": ["unicode handling"],
            "not_decided": ["the maximum length"],
        }

    def contract(call):
        return dict(SLUG_CONTRACT)

    def findings(call):
        closing = "closing read" in call.user
        f = knobs.findings()
        n = 0
        sev = "minor"
        if f and f[0] == call.role:
            n, sev = f[1], f[2]
        if closing:
            n = 1 if knobs.closing_files_finding() else 0
        cites = (
            _ids_of_kind(call.user, "C")
            or _ids_of_kind(call.user, "P")
            or _ids_of_kind(call.user, "K")
            or _ids_of_kind(call.user, "H")
            or ["C-0001"]
        )
        items = [
            {
                "severity": sev,
                "cites": [cites[i % len(cites)]],
                "kind": "finding",
                "klass": "actionable" if sev != "minor" else "noise",
                "argument": f"the clause {cites[i % len(cites)]} leaves the boundary case unstated for an empty input, which a reasonable implementer resolves two ways",
            }
            for i in range(n)
        ]
        return {"findings": items, "verdict": "REVISE" if items else "APPROVED"}

    def arbitrated(schema_key: str, model):
        def fn(call):
            section = (
                call.user.split("## The findings", 1)[1].split("## The", 1)[0]
                if "## The findings" in call.user
                else ""
            )
            handed = sorted(set(_ids_of_kind(section, "F")))
            current = store.read(schema_key, model)
            return {
                "decisions": [
                    {
                        "id": i,
                        "status": "accepted",
                        "arbitration": "stated the empty-input case in the clause and the failure policy",
                    }
                    for i in handed
                ],
                "artifact": current.wire_dump(),
            }

        return fn

    def vspec(call):
        c = store.read("contract", Contract)
        k = c.key_to_id()
        return {
            "properties": [
                {
                    "cites": [k["inv_charset"]],
                    "over": "output",
                    "klass": 1,
                    "family": "ascii text with punctuation",
                    "boundary": "punctuation runs",
                    "observe": "the set of characters of the result",
                    "falsifies": "a character outside a-z0-9- appears",
                    "tolerance": [],
                },
                {
                    "cites": [k["inv_words"], k["slugify"]],
                    "over": "input",
                    "klass": 2,
                    "family": "words separated by spaces and punctuation",
                    "boundary": "leading and trailing separators",
                    "observe": "the result compared to the lowercased words joined by hyphens",
                    "falsifies": "a word is missing, reordered or not lowercased",
                    "tolerance": [],
                },
                {
                    "cites": [k["fail_none"]],
                    "over": "input",
                    "klass": 6,
                    "family": "None",
                    "boundary": "the only non-str input the policy names",
                    "observe": "the exception type",
                    "falsifies": "no TypeError is raised",
                    "tolerance": [],
                },
                {
                    "cites": [k["inv_len"], k["max_len"]],
                    "over": "output",
                    "klass": 4,
                    "family": "long inputs",
                    "boundary": "exactly at and past MAX_LEN",
                    "observe": "the length of the result",
                    "falsifies": "a result longer than MAX_LEN",
                    "tolerance": [],
                },
                {
                    "cites": [k["neg_unicode"]],
                    "over": "input",
                    "klass": 5,
                    "family": "words with non-ascii letters",
                    "boundary": "an accented letter inside a word",
                    "observe": "the result for a word containing a non-ascii letter",
                    "falsifies": "the non-ascii letter is transliterated instead of splitting the word",
                    "tolerance": [],
                },
            ],
            "contract_gaps": [],
        }

    def files(call):
        c = store.read("contract", Contract)
        k = c.key_to_id()
        module = store.read("plan", Plan).blocks[0].name
        if call.fixture in ("tests", "fix-tests"):
            v = store.read("vspec", VerificationSpec)
            pids = [p.id or "" for p in v.properties]
            while len(pids) < 5:
                pids.append(f"P-{len(pids) + 1:04d}")
            src = TESTS.format(MODULE=module, **{f"P{i + 1}": pids[i].replace("-", "_") for i in range(5)})
            return {
                "files": [{"path": f"tests/test_{module}.py", "content": src}],
                "report": {"steps": pids[:5], "notes": [], "blocked": False},
            }
        buggy = os.environ.get("FAKE_IMPL") == "buggy" and call.fixture == "implement"
        src = (IMPL_BUGGY if buggy else IMPL_OK).format(
            S_NONE=k["s_none"], S_LOWER=k["s_lower"], S_JOIN=k["s_join"]
        )
        return {
            "files": [{"path": f"src/{module}.py", "content": src}],
            "report": {"steps": [k["s_none"], k["s_lower"], k["s_join"]], "notes": [], "blocked": False},
        }

    def ruling(call):
        q = 1 if "ruling-q1" in (call.fixture or "") else 2
        pid = (re.search(r"P-\d{4}", call.user) or re.search(r"P-\d{4}", "P-0001")).group(0)
        v = knobs.verdict()
        verdict = v[1] if v and v[0] == call.role else ("test_stands" if q == 1 else "implementation_bug")
        cites = _ids_of_kind(call.user, "C") or ["C-0001"]
        readings = (
            ["the words are lowercased", "the words keep their case"]
            if verdict == "contract_ambiguity"
            else []
        )
        return {
            "property": pid,
            "question": q,
            "verdict": verdict,
            "cites": cites[:1],
            "readings": readings,
            "argument": "the test reads the clause as written: the words must appear lowercased, and the observed assertion shows they did not, so the failing side is the code",
            "consequence": "the implementer lowercases before joining"
            if q == 2
            else "the test stands as written",
        }

    return {
        "AssumptionsLedger": ledger,
        "Plan": plan,
        "Contract": contract,
        "Findings": findings,
        "ArbitratedPlan": arbitrated("plan", Plan),
        "ArbitratedContract": arbitrated("contract", Contract),
        "ArbitratedVerificationSpec": arbitrated("vspec", VerificationSpec),
        "VerificationSpec": vspec,
        "FilesAuthor": files,
        "Ruling": ruling,
    }
