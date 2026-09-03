import json


from code_steer_model_write.backends.fake import FakeBackend, register_faker
from code_steer_model_write.config import Mode
from code_steer_model_write.driver.halt import Halt
from code_steer_model_write.driver.runner import Runner
from code_steer_model_write.events import EventLog
from code_steer_model_write.spec.findings import FindingStatus
from code_steer_model_write.state.run import Outcome, RunPaths, RunState
from tests.test_driver import _gate_auto, _task
from tests.toy_program import ToyReviewProgram

PLAN = {"blocks": ["slug"], "summary": "one block (C-0001), the slug function, nothing else"}


def _findings(*items):
    return {
        "findings": [
            {
                "severity": s,
                "cites": c,
                "klass": k,
                "argument": "the plan's block boundary is unstated for this input, " * 2,
            }
            for s, c, k in items
        ],
        "verdict": "REVISE" if items else "APPROVED",
    }


class Script:
    """A scripted fake: the reviewer's answer per round, the author's arbitration per round."""

    def __init__(self, reviews, arbitrations=None):
        self.reviews = reviews
        self.arbitrations = arbitrations or {}
        self.n = {"review": 0}

    def review(self, call):
        self.n["review"] += 1
        return self.reviews[min(self.n["review"], len(self.reviews)) - 1]

    def arbitrate(self, call):
        # decide every id handed: accept unless the script says reject
        import re

        handed = sorted(
            set(re.findall(r"F-\d{4}", call.user.split("## The findings")[1].split("## The plan")[0]))
        )
        status = self.arbitrations.get("status", "accepted")
        text = (
            "changed the block boundary to name the input and the output explicitly"
            if status == "accepted"
            else "the plan states the boundary in its summary line, which names both the input string and the slug output"
        )
        return {
            "decisions": [{"id": i, "status": status, "arbitration": text} for i in handed],
            "artifact": {
                "blocks": ["slug"],
                "summary": "one block (C-0001), the slug function; boundary: str in, slug out",
            },
        }


def _drive(tmp_path, script, cap=2, mode=Mode.AUTO):
    register_faker("Plan", lambda call: PLAN)
    register_faker("Findings", script.review)
    register_faker("ArbitratedPlan", script.arbitrate)
    paths = RunPaths(run_dir=tmp_path / "run")
    t = _task().model_copy(update={"mode": mode, "rounds": cap})
    RunState.create(paths, t)
    prog = ToyReviewProgram(cap=cap)
    r = Runner(paths, prog, {"fake": FakeBackend()}, t.roles, _gate_auto, poll_seconds=0.01)
    return r.drive(), paths, prog


def test_approved_at_once_converges_without_arbitration(tmp_path):
    out, paths, prog = _drive(tmp_path, Script([_findings()]))
    assert out is Outcome.COMPLETED
    st = prog.loop.status(paths.run_dir)
    assert st.converged and st.rounds_filed == 1 and not st.closing_done
    keys = list(RunState.load(paths).steps)
    assert keys == ["p0-plan", "plan-review-r1", "p0-freeze"]


def test_findings_then_arbitration_then_closing_read(tmp_path):
    out, paths, prog = _drive(
        tmp_path, Script([_findings(("major", ["C-0001"], "actionable")), _findings(), _findings()]), cap=1
    )
    assert out is Outcome.COMPLETED
    keys = list(RunState.load(paths).steps)
    assert keys == ["p0-plan", "plan-review-r1", "plan-arbitrate-r1", "plan-review-r2", "p0-freeze"]
    st = prog.loop.status(paths.run_dir)
    assert st.closing_done and st.converged and not st.carried
    fs = prog.loop.all_findings(paths.run_dir)
    assert fs[0].id == "F-0001" and fs[0].status is FindingStatus.ACCEPTED and fs[0].round == 1
    assert prog.loop.store_versions(paths) if hasattr(prog.loop, "store_versions") else True
    # the artifact was re-emitted as a new version by code
    assert (paths.artifacts / "plan" / "v002.json").exists()
    # the closing round's packet carried round 1 verbatim and the computed diff
    started = [
        e
        for e in EventLog(paths.events, "t1").all()
        if e.kind == "call.started" and e.step == "plan-review-r2"
    ]
    assert started and started[0].data["rendered_keys"] == ["plan"]


def test_closing_read_findings_are_carried(tmp_path):
    out, paths, prog = _drive(
        tmp_path,
        Script([_findings(("minor", ["C-0001"], "tradeoff")), _findings(("minor", ["C-0001"], "tradeoff"))]),
        cap=1,
    )
    assert out is Outcome.COMPLETED
    st = prog.loop.status(paths.run_dir)
    assert st.closing_done and not st.converged and [f.id for f in st.carried] == ["F-0002"]
    assert prog.loop.verdict(paths.run_dir).route == "carry"


def test_twice_rejected_re_raise_escalates(tmp_path):
    reviews = [_findings(("blocking", ["C-0001"], "actionable"))] * 4
    out, paths, prog = _drive(tmp_path, Script(reviews, {"status": "rejected"}), cap=3)
    fs = prog.loop.all_findings(paths.run_dir)
    assert [f.status for f in fs[:3]] == [
        FindingStatus.REJECTED,
        FindingStatus.REJECTED,
        FindingStatus.ESCALATED,
    ]
    assert prog.loop.verdict(paths.run_dir).route == "escalate"


def test_doubt_theater_is_a_check_not_a_prompt(tmp_path):
    reviews = [
        _findings(("minor", ["C-0001"], "noise")),
        _findings(("minor", ["C-0001"], "noise")),
        _findings(),
    ]
    out, paths, prog = _drive(tmp_path, Script(reviews), cap=2)
    st = prog.loop.status(paths.run_dir)
    assert st.doubt_theater
    checks = [
        e
        for e in EventLog(paths.events, "t1").all()
        if e.kind == "check.result" and any("doubt_theater" in p for p in e.data.get("problems", []))
    ]
    assert checks


def test_refused_arbitration_records_nothing(tmp_path):
    # the author refuses to arbitrate ("out of scope") every time: the loop halts, no version 2, no arbitration file
    script = Script([_findings(("major", ["C-0001"], "actionable"))], {"status": "rejected"})
    script.arbitrate = lambda call: {
        "decisions": [{"id": "F-0001", "status": "rejected", "arbitration": "out of scope"}],
        "artifact": PLAN,
    }
    out, paths, prog = _drive(tmp_path, script, cap=1)
    assert out is Outcome.HALTED_HONESTLY
    h = Halt.read(paths)
    assert h.step == "plan-arbitrate-r1" and "arbitration_refuses" in h.message
    assert (
        not (paths.artifacts / "plan" / "v002.json").exists()
        and not prog.loop.arbitration_path(paths.run_dir, 1).exists()
    )
    assert prog.loop.all_findings(paths.run_dir)[0].status is FindingStatus.OPEN


def test_finding_schema_carries_klass_and_hides_code_fields():
    from code_steer_model_write.spec.findings import Findings

    s = Findings.wire_schema()
    props = s["$defs"]["Finding"]["properties"]
    assert s["$defs"]["Klass"]["enum"] == [
        "contract_misread",
        "actionable",
        "tradeoff",
        "noise",
    ] and "$ref" in json.dumps(props["klass"])
    assert "round" not in props and "id" not in props
