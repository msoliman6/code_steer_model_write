"""The gate record and the mode dial (rule 11).

`gates/<id>.ask.json` is the one record of a gate; every renderer (page, tty, auto-answerer)
derives from it. `gates/<id>.decision.json` is the answer, written by the human's form or by
the auto-answerer, atomically. `decisions.json` folds every decision of the run.
"""

from __future__ import annotations

import json
from typing import Callable

from ..backends import knobs
from ..config import Mode
from ..driver.steps import ProgramContext, Step
from ..ids import Prefix, next_id
from ..spec.decisions import Decision, DecisionRecord, Gate, GateDecision
from ..state.lock import atomic_write_text, locked
from ..state.run import RunPaths

GateBuilder = Callable[[Step, ProgramContext], Gate]


def ask_path(paths: RunPaths, gate_id: str):
    return paths.gates / f"{gate_id}.ask.json"


def decision_path(paths: RunPaths, gate_id: str):
    return paths.gates / f"{gate_id}.decision.json"


def write_ask(paths: RunPaths, gate: Gate) -> None:
    atomic_write_text(ask_path(paths, gate.id), gate.model_dump_json(indent=2))


def read_ask(paths: RunPaths, gate_id: str) -> Gate | None:
    p = ask_path(paths, gate_id)
    return Gate.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None


def read_decision(paths: RunPaths, gate_id: str) -> GateDecision | None:
    p = decision_path(paths, gate_id)
    return GateDecision.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None


def write_decision(paths: RunPaths, d: GateDecision) -> None:
    atomic_write_text(decision_path(paths, d.gate), d.model_dump_json(indent=2))


def auto_decision(gate: Gate) -> GateDecision:
    """Every question takes its default (or the recommended answer) and is flagged."""
    action = "proceed"
    r = knobs.revise()
    if r and r[0] == gate.name and gate.round <= r[1] and gate.can_revise:
        action = "revise"
    return GateDecision(
        gate=gate.id,
        action=action,
        source="auto",
        decisions=[
            Decision(question_id=q.id, answer=q.recommended or q.default, answered_by="auto", flagged=True)
            for q in gate.questions
        ],
    )


def fold(paths: RunPaths, gate: Gate, d: GateDecision) -> list[DecisionRecord]:
    """Append the gate's decisions to decisions.json under the lock; ids assigned by code."""
    with locked(paths.decisions):
        rows: list[DecisionRecord] = []
        if paths.decisions.exists():
            rows = [
                DecisionRecord.model_validate(r)
                for r in json.loads(paths.decisions.read_text(encoding="utf-8"))
            ]
        taken = [r.id for r in rows]
        qtext = {q.id: q.text for q in gate.questions}
        new: list[DecisionRecord] = []
        for dec in d.decisions:
            rid = next_id(Prefix.DECISION, taken)
            taken.append(rid)
            new.append(
                DecisionRecord(
                    id=rid,
                    gate=gate.id,
                    question_id=dec.question_id,
                    question=qtext.get(dec.question_id, ""),
                    answer=dec.answer,
                    answered_by=dec.answered_by,
                    flagged=dec.flagged,
                    comment=dec.comment,
                )
            )
        rows += new
        atomic_write_text(paths.decisions, json.dumps([r.model_dump(mode="json") for r in rows], indent=2))
    return new


def flagged_decisions(paths: RunPaths) -> list[DecisionRecord]:
    if not paths.decisions.exists():
        return []
    return [
        r
        for r in (
            DecisionRecord.model_validate(x) for x in json.loads(paths.decisions.read_text(encoding="utf-8"))
        )
        if r.flagged
    ]


def make_waiter(mode: Mode, builders: dict[str, GateBuilder]):
    """The Runner's gate waiter. Writes the ask record once; auto-answers when the mode says
    so (flagged); otherwise reports the wait (never silence) and returns False until a
    decision file exists. A gate with nothing to ask and nothing carried is not issued by a
    well-formed program (rule 9); if one arrives, it is auto-proceeded and recorded."""

    def waiter(step: Step, ctx: ProgramContext) -> bool:
        assert step.gate
        paths = ctx.paths
        gate = read_ask(paths, step.gate)
        if gate is None:
            gate = builders[step.gate.split(".", 1)[0]](step, ctx)
            write_ask(paths, gate)
            ctx.events.append(
                "gate.asked",
                step=step.key,
                gate=gate.id,
                kind=gate.kind,
                title=gate.title,
                questions=len(gate.questions),
                carried=len(gate.carried),
                needs_human=gate.needs_human(mode.value),
            )
        d = read_decision(paths, gate.id)
        if d is None:
            empty = not gate.questions and not gate.carried
            if empty or not gate.needs_human(mode.value):
                d = auto_decision(gate)
                write_decision(paths, d)
                fold(paths, gate, d)
                ctx.events.append(
                    "gate.decided",
                    step=step.key,
                    gate=gate.id,
                    action=d.action,
                    source="auto",
                    flagged=d.flagged_ids,
                    empty=empty,
                )
                if d.flagged_ids:
                    ctx.events.append("decision.auto", step=step.key, gate=gate.id, flagged=d.flagged_ids)
                return True
            return False
        if not (paths.gates / f"{gate.id}.folded").exists():
            fold(paths, gate, d)
            (paths.gates / f"{gate.id}.folded").write_text("1")
            ctx.events.append(
                "gate.decided",
                step=step.key,
                gate=gate.id,
                action=d.action,
                source=d.source,
                flagged=d.flagged_ids,
                comments=list(d.comments),
            )
        return True

    return waiter
