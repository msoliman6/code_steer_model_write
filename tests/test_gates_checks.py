import json


from code_steer_model_write.backends.fake import FakeBackend, register_faker
from code_steer_model_write.checks.code import banned_words, cites_resolve, no_minted_ids, set_difference
from code_steer_model_write.config import Mode
from code_steer_model_write.driver.runner import Runner
from code_steer_model_write.events import EventLog
from code_steer_model_write.gates.gate import (
    flagged_decisions,
    make_waiter,
    read_ask,
    read_decision,
    write_decision,
)
from code_steer_model_write.spec.base import CheckContext
from code_steer_model_write.spec.decisions import Decision, Gate, GateDecision, Question
from code_steer_model_write.spec.findings import (
    Arbitrated,
    ArbitrationDecision,
    Finding,
    Findings,
    FindingStatus,
    Severity,
    Verdict,
)
from code_steer_model_write.state.run import Outcome, RunPaths, RunState
from tests.test_driver import _task
from tests.toy_program import Plan, ToyProgram


def _gate_builder(step, ctx):
    return Gate(
        id=step.gate,
        name="blocks",
        kind="judgment",
        title="Confirm the blocks",
        questions=[
            Question(
                id="Q-0001",
                text="Keep the slug block as one unit?",
                kind="confirm",
                default="yes",
                risky=False,
            )
        ],
    )


def _risky_builder(step, ctx):
    g = _gate_builder(step, ctx)
    g.questions[0].risky = True
    return g


def _run(tmp_path, mode, builder, **kw):
    register_faker(
        "Plan", lambda call: {"blocks": ["slug"], "summary": "one block, the slug function, nothing else"}
    )
    paths = RunPaths(run_dir=tmp_path / "run")
    t = _task().model_copy(update={"mode": mode})
    RunState.create(paths, t)
    r = Runner(
        paths,
        ToyProgram(),
        {"fake": FakeBackend()},
        t.roles,
        make_waiter(mode, {"blocks": builder}),
        poll_seconds=0.01,
        **kw,
    )
    return r, paths


def test_auto_mode_answers_and_flags(tmp_path):
    r, paths = _run(tmp_path, Mode.AUTO, _gate_builder)
    assert r.drive() is Outcome.COMPLETED
    d = read_decision(paths, "blocks")
    assert d.source == "auto" and d.flagged_ids == ["Q-0001"] and d.decisions[0].answer == "yes"
    assert [x.question_id for x in flagged_decisions(paths)] == ["Q-0001"]
    kinds = [e.kind for e in EventLog(paths.events, "t1").all()]
    assert "gate.asked" in kinds and "decision.auto" in kinds
    assert read_ask(paths, "blocks").title == "Confirm the blocks"


def test_light_mode_skips_a_safe_judgment_and_asks_a_risky_one(tmp_path):
    r, paths = _run(tmp_path, Mode.LIGHT, _gate_builder)
    assert r.drive() is Outcome.COMPLETED and read_decision(paths, "blocks").source == "auto"
    r2, paths2 = _run(tmp_path / "b", Mode.LIGHT, _risky_builder, gate_timeout=0.05)
    assert r2.drive() is Outcome.HALTED_HONESTLY  # waited for the human, never silent
    asked = [e for e in EventLog(paths2.events, "t1").all() if e.kind == "gate.asked"]
    assert asked and asked[0].data["needs_human"] is True
    write_decision(
        paths2,
        GateDecision(
            gate="blocks",
            action="proceed",
            source="human",
            decisions=[Decision(question_id="Q-0001", answer="no", answered_by="human")],
            comments={"slug": "split it"},
        ),
    )
    r3 = Runner(
        paths2,
        ToyProgram(),
        {"fake": FakeBackend()},
        _task().roles,
        make_waiter(Mode.LIGHT, {"blocks": _risky_builder}),
        poll_seconds=0.01,
    )
    assert r3.drive() is Outcome.COMPLETED
    rows = json.loads(paths2.decisions.read_text())
    assert rows[0]["answered_by"] == "human" and rows[0]["flagged"] is False and rows[0]["id"] == "D-0001"


def test_fake_revise_knob(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REVISE", "blocks:1")
    r, paths = _run(tmp_path, Mode.AUTO, _gate_builder)
    r.drive()
    assert read_decision(paths, "blocks").action == "revise"


def test_verdict_routes_by_severity():
    f = [
        Finding(id="F-0001", severity=Severity.MINOR, cites=["C-0001"], argument="a" * 50),
        Finding(id="F-0002", severity=Severity.BLOCKING, cites=["C-0001"], argument="a" * 50),
    ]
    assert Verdict.of(f).route == "revise" and Verdict.of(f).worst is Severity.BLOCKING
    assert Verdict.of(f, cap_reached=True).route == "escalate"
    f[1].status = FindingStatus.ACCEPTED
    assert Verdict.of(f, cap_reached=True).route == "carry"
    assert Verdict.of([]).route == "pass"


def test_findings_and_arbitration_semantics():
    ctx = CheckContext(known_ids={"C-0001"}, extra={"finding_ids": ["F-0001"]})
    fs = Findings(findings=[], verdict="REVISE")
    assert fs.semantic_problems(ctx)[0].code == "verdict_contradicts"
    arb = Arbitrated[Plan](
        decisions=[ArbitrationDecision(id="F-0001", status="rejected", arbitration="out of scope")],
        artifact=Plan(blocks=["slug"], summary="one block, the slug function"),
    )
    codes = [p.code for p in arb.semantic_problems(ctx)]
    assert codes == ["arbitration_refuses"]
    arb2 = Arbitrated[Plan](
        decisions=[
            ArbitrationDecision(
                id="F-0002", status="accepted", arbitration="split the slug block into parse and join"
            )
        ],
        artifact=arb.artifact,
    )
    assert [p.code for p in arb2.semantic_problems(ctx)] == ["decisions_mismatch"]
    # the schema the backend sees has no id/status/arbitration fields on a finding (code assigns them)
    props = Findings.wire_schema()["$defs"]["Finding"]["properties"]
    assert "id" not in props and "status" not in props and "argument" in props


def test_code_checks():
    ctx = CheckContext(known_ids={"C-0001"})
    f = Findings(
        findings=[
            Finding(severity=Severity.MINOR, cites=["C-0009"], argument="handles errors gracefully " * 5)
        ],
        verdict="REVISE",
    )
    assert cites_resolve(f, ctx)[0].message.startswith("C-0009")
    assert no_minted_ids(f, ctx)[0].code == "id_minted"
    bw = banned_words(["gracefully", "appropriately"])
    assert bw(f, ctx)[0].code == "banned_word" and "findings[0].argument" in bw(f, ctx)[0].path
    probs = set_difference({"A-0001", "A-0002"}, {"A-0002", "A-0003"}, what="steps")
    assert [p.code for p in probs] == ["steps_missing", "steps_extra"]


def test_gate_needs_human_rules():
    g = Gate(
        id="x.r1", name="x", kind="input", title="t", questions=[Question(id="Q-0001", text="?", default="a")]
    )
    assert g.needs_human("light") and g.needs_human("detailed") and not g.needs_human("auto")
    j = Gate(id="y.r1", name="y", kind="judgment", title="t")
    assert not j.needs_human("light")
    j.carried = [{"id": "F-0001"}]
    assert j.needs_human("light")
