import pytest

from code_steer_model_write.ask import CallContext, FnCheck, ask
from code_steer_model_write.backends.fake import FakeBackend, register_faker
from code_steer_model_write.config import BackendName, RoleSpec
from code_steer_model_write.events import EventLog
from code_steer_model_write.prompts import PromptError, Template, fill
from code_steer_model_write.spec.base import CheckContext, Problem


def _ctx(tmp_path, **kw):
    log = EventLog(tmp_path / "events.jsonl", "r1")
    return CallContext(
        backend=FakeBackend(),
        role_spec=RoleSpec(backend=BackendName.FAKE, model="fake-1"),
        events=log,
        step="s1",
        check_ctx=CheckContext(known_ids={"C-0001"}),
        **kw,
    ), log


@pytest.fixture
def prompt(finding_models):
    _, Findings = finding_models
    register_faker(
        "Findings",
        lambda call: {
            "findings": [{"severity": "major", "cites": ["C-0001"], "argument": "a" * 50}],
            "verdict": "REVISE",
        },
    )
    t = Template(name="review", text="Review this:\n\n{{ARTIFACT_MD}}\n", keys=["ARTIFACT_MD"])
    return fill(
        t, {"ARTIFACT_MD": "## Contract\n\n- **x**: 1\n"}, schema=Findings, rendered_keys=["contract"]
    )


def test_fill_refuses_missing_unused_and_raw_json(finding_models):
    _, Findings = finding_models
    t = Template(name="t", text="{{A}}", keys=["A"])
    with pytest.raises(PromptError, match="no value"):
        fill(t, {}, schema=Findings)
    with pytest.raises(PromptError, match="no key"):
        fill(t, {"A": "x", "B": "y"}, schema=Findings)
    with pytest.raises(PromptError, match="raw JSON"):
        fill(t, {"A": '{"k": 1}'}, schema=Findings)
    p = fill(t, {"A": "text"}, schema=Findings)
    assert "no tools, no files, no shell" in p.system and "Findings" in p.system and '"verdict"' in p.system


def test_accepted_first_attempt(tmp_path, prompt, finding_models):
    _, Findings = finding_models
    ctx, log = _ctx(tmp_path)
    r = ask(prompt, Findings, role="reviewer", ctx=ctx)
    assert r.attempts == 1 and r.value.verdict == "REVISE" and r.usage.total > 0
    kinds = [e.kind for e in log.all()]
    assert kinds == ["call.started", "call.usage", "call.final", "check.result"]
    assert log.all()[0].data["tools"] == [] and log.all()[0].data["rendered_keys"] == ["contract"]


def test_re_ask_recovers_at_n_plus_one(tmp_path, prompt, finding_models, monkeypatch):
    _, Findings = finding_models
    monkeypatch.setenv("FAKE_REFUSE", "reviewer:2")
    ctx, log = _ctx(tmp_path)
    r = ask(prompt, Findings, role="reviewer", ctx=ctx)
    assert r.attempts == 3
    refused = [e for e in log.all() if e.kind == "step.refused"]
    assert len(refused) == 2 and any("schema." in p for p in refused[0].data["problems"])
    # the re-ask carried the exact problems and the refused answer
    assert "artifact.written" not in [e.kind for e in log.all()]


def test_no_progress_stops_before_cap(tmp_path, prompt, finding_models, monkeypatch):
    _, Findings = finding_models
    monkeypatch.setenv("FAKE_REFUSE", "reviewer:same")
    ctx, log = _ctx(tmp_path)
    r = ask(prompt, Findings, role="reviewer", ctx=ctx)
    assert r.reason == "no_progress" and len(r.problems_by_attempt) == 2
    assert r.last_answer is not None and "__fake_extra__" in r.last_answer


def test_cap_when_problems_keep_changing(tmp_path, prompt, finding_models):
    _, Findings = finding_models
    n = {"i": 0}

    def changing(answer, ctx):
        n["i"] += 1
        return [Problem(code=f"p{n['i']}", message="different every time")]

    ctx, log = _ctx(tmp_path)
    r = ask(prompt, Findings, role="reviewer", ctx=ctx, checks=[FnCheck("changing", changing)])
    assert r.reason == "cap" and len(r.problems_by_attempt) == 6


def test_semantic_problem_refuses_and_backend_error_halts(tmp_path, prompt, finding_models, monkeypatch):
    _, Findings = finding_models
    ctx, log = _ctx(tmp_path)
    ctx.check_ctx = CheckContext(known_ids=set())  # C-0001 no longer resolves
    r = ask(prompt, Findings, role="reviewer", ctx=ctx)
    assert r.reason == "no_progress" and "cite_unresolved" in r.problems_by_attempt[0][0]
    monkeypatch.setenv("FAKE_TOOLLESS_VIOLATION", "reviewer")
    ctx2, log2 = _ctx(tmp_path / "b")
    r2 = ask(prompt, Findings, role="reviewer", ctx=ctx2)
    assert r2.reason == "backend" and "tool call" in r2.message
    assert [e.kind for e in log2.all()][-1] == "call.error"
