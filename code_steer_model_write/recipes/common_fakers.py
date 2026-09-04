"""Fake answers for the shapes the template owns (the assumptions ledger and findings), so a
recipe's own fakers only cover its own shapes and no recipe imports another's (plan §12). The
knobs drive the branches exactly as the bundled recipes' fakers do."""

from __future__ import annotations

from typing import Any, Callable

from ..artifacts.store import Store
from ..backends import knobs
from ..state.run import RunPaths
from .base import ids_of_kind


def common_fakers(paths: RunPaths, store: Store) -> dict[str, Callable[[Any], dict[str, Any]]]:
    def ledger(call):
        return {
            "rows": [
                {
                    "assumption": "the request means what it says and nothing more",
                    "basis": "the brief's request",
                    "if_wrong": "the plan solves a neighbouring problem",
                    "confirm": "unknown",
                },
                {
                    "assumption": "one deliverable, checked by the other side",
                    "basis": "the brief's surface",
                    "if_wrong": "the plan needs a second block",
                    "confirm": "unknown",
                },
            ],
            "queue": [],
        }

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
            ids_of_kind(call.user, "C")
            or ids_of_kind(call.user, "P")
            or ids_of_kind(call.user, "K")
            or ids_of_kind(call.user, "H")
            or ["C-0001"]
        )
        items = [
            {
                "severity": sev,
                "cites": [cites[i % len(cites)]],
                "kind": "finding",
                "klass": "actionable" if sev != "minor" else "noise",
                "argument": f"the clause {cites[i % len(cites)]} leaves the boundary case unstated for an empty input, which a reasonable reader resolves two ways",
            }
            for i in range(n)
        ]
        return {"findings": items, "verdict": "REVISE" if items else "APPROVED"}

    return {"AssumptionsLedger": ledger, "Findings": findings}


def arbitrated(store: Store, schema_key: str, model) -> Callable[[Any], dict[str, Any]]:
    """An arbitration that accepts every handed finding and returns the current artifact."""

    def fn(call):
        section = (
            call.user.split("## The findings", 1)[1].split("## The", 1)[0]
            if "## The findings" in call.user
            else ""
        )
        handed = sorted(set(ids_of_kind(section, "F")))
        current = store.read(schema_key, model)
        return {
            "decisions": [
                {
                    "id": i,
                    "status": "accepted",
                    "arbitration": "stated the boundary case in the clause itself",
                }
                for i in handed
            ],
            "artifact": current.wire_dump(),
        }

    return fn
