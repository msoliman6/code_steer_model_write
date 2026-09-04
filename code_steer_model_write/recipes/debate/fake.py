"""The debate recipe's fake answers (rule 12). FAKE_VERDICT=checker:undecided walks the human
ruling; FAKE_FINDINGS walks the review rounds on the hypotheses."""

from __future__ import annotations

import re
from typing import Any, Callable

from ...artifacts.debate import Case, Hypotheses
from ...artifacts.store import Store
from ...backends import knobs
from ...state.run import RunPaths
from ..base import ids_of_kind as _ids_of_kind


def fakers(paths: RunPaths, store: Store) -> dict[str, Callable[[Any], dict[str, Any]]]:
    from ..common_fakers import common_fakers

    base = common_fakers(paths, store)

    def hypotheses(call):
        return {
            "hypotheses": [
                {
                    "key": "caching",
                    "claim": "prompt caching cuts the cost of a review round by more than half when the packet is stable",
                    "falsifier": "a measured round with a stable packet whose cache-read tokens are under half its input",
                    "assumptions": ["the packet prefix is byte-stable"],
                },
                {
                    "key": "rounds",
                    "claim": "a second review round finds fewer actionable findings than the first on every artifact",
                    "falsifier": "an artifact where round two files more actionable findings than round one",
                    "assumptions": [],
                },
            ],
            "chosen": "caching",
        }

    def arb_h(call):
        section = (
            call.user.split("## The findings", 1)[1].split("## The", 1)[0]
            if "## The findings" in call.user
            else ""
        )
        handed = sorted(set(_ids_of_kind(section, "F")))
        return {
            "decisions": [
                {
                    "id": i,
                    "status": "accepted",
                    "arbitration": "restated the falsifier as a measurement the run itself records",
                }
                for i in handed
            ],
            "artifact": store.read("hypotheses", Hypotheses).wire_dump(),
        }

    def case(call):
        h = store.read("hypotheses", Hypotheses).chosen_id()
        side = "support" if call.fixture == "support" else "challenge"
        if side == "support":
            args = [
                {
                    "key": "prefix",
                    "text": "the packet renders the same artifact, history and diff in the same order every round, so the prefix is stable by construction",
                    "evidence": "render() is pure: same JSON, same markdown; the events record the prompt hash per call",
                    "cites": [h],
                },
                {
                    "key": "measured",
                    "text": "the run report's waste table shows cache reads above half of input tokens on stable rounds in the reference runs",
                    "evidence": "RUN-REPORT-2026-08-29 token columns",
                    "cites": [h],
                },
            ]
        else:
            support_ids = (
                [a.id for a in store.read("support", Case).arguments if a.id]
                if store.exists("support")
                else []
            )
            args = [
                {
                    "key": "diff",
                    "text": "the computed diff changes every round by definition, and it sits before the history in the packet, so the stable prefix ends early",
                    "evidence": "packet() order: artifact, rule, history, diff",
                    "cites": [h] + support_ids[:1],
                },
                {
                    "key": "minimum",
                    "text": "a small artifact never reaches the minimum cacheable prefix, so the saving is zero on exactly the runs a hackathon makes",
                    "evidence": "the 512 to 4096 token minimum per model",
                    "cites": [h],
                },
            ]
        return {"side": side, "arguments": args}

    def rebuttal(call):
        ids = [a.id for a in store.read("challenge", Case).arguments if a.id]  # the record, not the prose
        items = []
        for i, x in enumerate(ids):
            if i == 0:
                items.append(
                    {
                        "id": x,
                        "status": "rebutted",
                        "text": "the diff is rendered after the history and the artifact, so the stable prefix covers the artifact and every prior round before it changes",
                    }
                )
            else:
                items.append(
                    {
                        "id": x,
                        "status": "conceded",
                        "text": "true for artifacts under the minimum; the claim now names the packet size",
                    }
                )
        return {
            "items": items,
            "revised_claim": "prompt caching cuts the cost of a review round by more than half when the packet is stable and longer than the model's minimum cacheable prefix",
        }

    def judge(call):
        rows = re.findall(r"\*\*([a-z_]+)\*\* \(weight", call.user)
        v = knobs.verdict()
        verdict = v[1] if v and v[0] == call.role else "supported"
        cites = _ids_of_kind(call.user, "X")[:2] or _ids_of_kind(call.user, "H")[:1]
        return {
            "scores": [
                {
                    "name": r,
                    "score": 7,
                    "reason": "the rebuttal answered the ordering argument with the packet's actual layout, and conceded the minimum honestly",
                }
                for r in rows
            ],
            "verdict": verdict,
            "argument": "the supporting case rests on a mechanism the code enforces, the surviving challenge only bounds it, and the revised claim states the bound; the ruling follows the rubric weights",
            "cites": cites,
        }

    base.update(
        {
            "Hypotheses": hypotheses,
            "ArbitratedHypotheses": arb_h,
            "Case": case,
            "Rebuttal": rebuttal,
            "Ruling": judge,
        }
    )
    return base
