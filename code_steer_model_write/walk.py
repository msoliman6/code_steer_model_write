"""The offline walk (rule 12): the whole recipe with the fake backend, zero tokens, every branch a
live run can enter, asserted from events.jsonl. `csmw walk <recipe>|all` runs every leg;
`bash scripts/run.sh` is the full suite."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from pydantic import BaseModel

from .artifacts.store import Store
from .backends.fake import FakeBackend
from .config import Mode
from .driver.halt import Halt
from .driver.runner import Runner
from .events import EventLog
from .gates.gate import make_waiter, write_decision
from .recipes import registry
from .recipes.base import Recipe
from .spec.decisions import Decision, GateDecision
from .spec.task import TaskSpec
from .state.run import Outcome, RunPaths, RunState

ROOT = Path(__file__).resolve().parent.parent


class LegResult(BaseModel):
    name: str
    ok: bool
    outcome: str
    seconds: float
    detail: str = ""
    run_dir: str = ""


@contextmanager
def env(**kv: str) -> Iterator[None]:
    old = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def fake_task(recipe: str, *, mode: Mode = Mode.AUTO, rounds: int = 1, task_id: str = "walk") -> TaskSpec:
    example = json.loads((ROOT / "examples" / recipe / "task.json").read_text())
    example.update(
        {
            "task_id": task_id,
            "mode": mode.value,
            "rounds": rounds,
            "roles": {
                r: {"backend": "fake", "model": f"fake-{s}"}
                for r, s in registry.get(recipe).spec.roles.items()
            },
        }
    )
    return TaskSpec.model_validate(example)


def make_runner(
    paths: RunPaths, recipe: Recipe, task: TaskSpec, *, gate_timeout: float | None = None
) -> Runner:
    store = Store(paths.run_dir)
    fake = FakeBackend(fixtures_root=recipe.fixtures_root, fakers=recipe.fakers(paths, store))
    return Runner(
        paths,
        recipe,
        {"fake": fake},
        task.roles,
        make_waiter(task.mode, recipe.gate_builders()),
        poll_seconds=0.02,
        gate_timeout=gate_timeout,
    )


def start(recipe_name: str, run_dir: Path, **kw: Any) -> tuple[RunPaths, Recipe, TaskSpec]:
    recipe = registry.get(recipe_name)
    task = fake_task(recipe_name, **kw)
    paths = RunPaths(run_dir=run_dir)
    RunState.create(paths, task)
    return paths, recipe, task


def events(paths: RunPaths) -> list[Any]:
    return EventLog(paths.events, RunState.load(paths).run_id).all()


def kinds(paths: RunPaths) -> list[str]:
    return [e.kind for e in events(paths)]


# ---- legs -------------------------------------------------------------------------------

Leg = Callable[[Path], str]  # returns a detail string; raises AssertionError on failure


def assert_layers(paths: RunPaths, *, expect_tools: bool) -> str:
    """The seams are wired (ARCHITECTURE.md section 4, across layers 1): every step that
    started had an allowing policy decision before it; every accepted answer had an
    after_answer verdict; every before_prompt hook was asked; every tool call was logged
    before it ran and ran in the sandbox. A hook that was never called is a known gap."""
    evs = events(paths)
    seq_of_decision: dict[str, int] = {}
    for e in evs:
        if e.kind == "policy.decision" and e.data.get("allow"):
            seq_of_decision.setdefault(e.data["resource"], e.seq)
    started = [e for e in evs if e.kind == "step.started"]
    assert started, "no step started"
    decisions = [e for e in evs if e.kind == "policy.decision"]
    assert len(decisions) >= len(started), f"{len(decisions)} decisions for {len(started)} started steps"
    for st in started:
        before = [d for d in decisions if d.seq < st.seq and d.data.get("allow")]
        assert before, f"step {st.step} started with no allowing decision before it"
    finals = [e for e in evs if e.kind == "call.final" and e.role]
    verdicts = [e for e in evs if e.kind == "rail.verdict"]
    assert {v.data["hook"] for v in verdicts} >= {"before_prompt", "after_answer"}, (
        "a rail hook was never asked"
    )
    assert sum(1 for v in verdicts if v.data["hook"] == "after_answer") >= len(finals), (
        "an answer had no verdict"
    )
    assert all(v.data.get("accept") is not False or v.data["problems"] for v in verdicts), (
        "a refusal with no problems"
    )
    called = [e for e in evs if e.kind == "tool.called"]
    results = [e for e in evs if e.kind == "tool.result"]
    runs = [e for e in evs if e.kind == "sandbox.run"]
    assert len(called) == len(results), "a tool call without its result"
    assert len(runs) >= len(called), "a tool call that did not run in the sandbox"
    if expect_tools:
        assert called, "no tool call was logged on a run that executes code"
        assert {c.data["gen_ai.tool.name"] for c in called} >= {"pytest"}, (
            "pytest did not go through the registry"
        )
    for c, r in zip(called, results, strict=True):
        assert c.data["gen_ai.tool.call.id"] == r.data["gen_ai.tool.call.id"], (
            "a result with the wrong call id"
        )
    return f"{len(decisions)} decisions, {len(verdicts)} verdicts, {len(called)} tool calls in the {runs[0].data['tier'] if runs else 'no'} tier"


def leg_happy(tmp: Path) -> str:
    paths, recipe, task = start("code_builder", tmp / "run")
    out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, f"outcome {out}: {Halt.read(paths)}"
    st = RunState.load(paths)
    ks = kinds(paths)
    assert "halt" not in ks and "step.refused" not in ks
    assert ks.count("gate.decided") >= 3 and all(
        e.data.get("source") == "auto" for e in events(paths) if e.kind == "gate.decided"
    )
    assert (paths.run_dir / "freeze.json").exists() and (paths.run_dir / "REPORT.md").exists()
    res = json.loads((paths.artifacts / "results" / "v001.json").read_text())
    assert all(p["real"] == "pass" and p["null"] == "fail" for p in res["properties"]), res
    for e in events(paths):
        if e.kind == "call.started":
            assert e.data["tools"] == [], "a tool-less step carried tools"
    assert st.completed_at is not None
    layers = assert_layers(paths, expect_tools=True)
    return f"{len(st.steps)} steps, {len(res['properties'])} properties pass, 0 halts; {layers}"


def leg_refuse_recover(tmp: Path) -> str:
    with env(FAKE_REFUSE="author:2"):
        paths, recipe, task = start("code_builder", tmp / "run")
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    refused = [e for e in events(paths) if e.kind == "step.refused"]
    assert refused and all(e.role == "author" for e in refused)
    # nothing written from a refused attempt: every artifact.written follows a check.result with no problems
    evs = events(paths)
    for i, e in enumerate(evs):
        if e.kind == "artifact.written" and e.step and e.step.startswith("p0-ledger"):
            prior = [x for x in evs[:i] if x.step == e.step and x.kind == "check.result"]
            assert prior and prior[-1].data["problems"] == []
    return f"{len(refused)} refusals re-asked, then recovered"


def leg_no_progress_halts_then_resume(tmp: Path) -> str:
    with env(FAKE_REFUSE="author:same"):
        paths, recipe, task = start("code_builder", tmp / "run")
        out = make_runner(paths, recipe, task).drive()
    h = Halt.read(paths)
    assert (
        out is Outcome.HALTED_HONESTLY and h and h.reason.value == "refused" and "same problems" in h.message
    ), h
    out2 = make_runner(paths, recipe, task).drive()
    assert out2 is Outcome.COMPLETED, Halt.read(paths)
    st = RunState.load(paths)
    assert st.resumed_count == 1 and st.last_halt and st.last_halt.startswith("HALT at ")
    return f"halted at {h.step}, resumed, completed"


def leg_findings_rounds_and_closing(tmp: Path) -> str:
    with env(FAKE_FINDINGS="checker:2:major"):
        paths, recipe, task = start("code_builder", tmp / "run", rounds=2)
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    filed = [e for e in events(paths) if e.kind == "finding.filed"]
    decided = [e for e in events(paths) if e.kind == "finding.decided"]
    assert filed and decided
    rounds = [e for e in events(paths) if e.kind == "round.closed"]
    assert any(e.data.get("closing") for e in rounds), "no closing read"
    # every finding is decided exactly once per round
    ids = [e.data["id"] for e in decided]
    assert len(ids) == len(set(ids))
    return f"{len(filed)} findings filed, {len(decided)} decided, {len(rounds)} rounds closed"


def leg_closing_carries(tmp: Path) -> str:
    with env(FAKE_FINDINGS="checker:1:minor", FAKE_CLOSING="finding"):
        paths, recipe, task = start("code_builder", tmp / "run", rounds=1)
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    carried = [e for e in events(paths) if e.kind == "round.closed" and e.data.get("carried")]
    assert carried, "the closing read's finding was not carried"
    rep = json.loads((paths.artifacts / "report" / "v001.json").read_text())
    assert any(c["kind"] == "finding" for c in rep["carried"]), rep["carried"]
    assert "carried" in (paths.run_dir / "REPORT.md").read_text().lower()
    return f"{len(rep['carried'])} carried into the report"


def leg_buggy_impl_triage_fix(tmp: Path) -> str:
    with env(FAKE_IMPL="buggy"):
        paths, recipe, task = start("code_builder", tmp / "run")
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    v1 = json.loads((paths.artifacts / "results" / "v001.json").read_text())
    failing = [p for p in v1["properties"] if p["real"] != "pass"]
    assert failing, "the buggy implementation passed everything"
    verdicts = [e for e in events(paths) if e.kind == "judge.verdict"]
    assert [v.data["question"] for v in verdicts[:2]] == [1, 2], verdicts
    assert (paths.artifacts / "results" / "v002.json").exists(), "no re-run after the fix"
    v2 = json.loads((paths.artifacts / "results" / "v002.json").read_text())
    assert all(p["real"] == "pass" for p in v2["properties"]), v2
    return f"{len(failing)} failing -> q1 test_stands -> q2 implementation_bug -> fixed -> pass"


def leg_test_bug_route(tmp: Path) -> str:
    with env(FAKE_IMPL="buggy", FAKE_VERDICT="author:test_bug"):
        paths, recipe, task = start("code_builder", tmp / "run")
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    verdicts = [e.data["verdict"] for e in events(paths) if e.kind == "judge.verdict"]
    assert verdicts and set(verdicts) == {"test_bug"}, verdicts
    assert any(k.startswith("p4-fix-tests") for k in RunState.load(paths).steps)
    return "q1 test_bug -> the checker fixed the tests -> re-run"


def leg_ambiguity_carried(tmp: Path) -> str:
    with env(FAKE_IMPL="buggy", FAKE_VERDICT="checker:contract_ambiguity"):
        paths, recipe, task = start("code_builder", tmp / "run")
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    rep = json.loads((paths.artifacts / "report" / "v001.json").read_text())
    assert any(c["kind"] == "ambiguity" for c in rep["carried"]), rep["carried"]
    assert not any(k.startswith("p4-fix") for k in RunState.load(paths).steps)
    return "q2 contract_ambiguity -> carried as a result, nothing fixed"


def leg_gate_revise(tmp: Path) -> str:
    with env(FAKE_REVISE="blocks:1"):
        paths, recipe, task = start("code_builder", tmp / "run")
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    keys = list(RunState.load(paths).steps)
    assert "p1-contract-revise-r1" in keys and "p1-gate-blocks-r2" in keys, keys
    assert (paths.artifacts / "contract" / "v002.json").exists(), "the revision was not a new version"
    return "blocks gate sent back once -> revise -> asked again -> proceed"


def leg_light_mode_waits_then_human(tmp: Path) -> str:
    paths, recipe, task = start("code_builder", tmp / "run", mode=Mode.LIGHT)
    out = make_runner(paths, recipe, task, gate_timeout=0.3).drive()
    assert out is Outcome.HALTED_HONESTLY and Halt.read(paths).step == "p0-gate-ledger", Halt.read(paths)
    asked = [e for e in events(paths) if e.kind == "gate.asked"]
    assert asked and asked[0].data["needs_human"] is True
    answered: list[str] = []
    for _ in range(4):
        h = Halt.read(paths)
        if h is None or h.reason.value != "cancelled":
            break
        gid = next(e.data["gate"] for e in reversed(events(paths)) if e.kind == "gate.asked")
        gate = json.loads((paths.gates / f"{gid}.ask.json").read_text())
        write_decision(
            paths,
            GateDecision(
                gate=gid,
                action="proceed",
                source="human",
                decisions=[
                    Decision(question_id=q["id"], answer=q.get("default") or "yes", answered_by="human")
                    for q in gate["questions"]
                ],
            ),
        )
        answered.append(gid)
        out = make_runner(paths, recipe, task, gate_timeout=0.3).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    rows = json.loads(paths.decisions.read_text())
    assert rows[0]["answered_by"] == "human" and not rows[0]["flagged"]
    auto = [e for e in events(paths) if e.kind == "gate.decided" and e.data.get("source") == "auto"]
    return f"light: human answered {answered}; auto-answered {len(auto)} safe gate(s); never silent"


def leg_debate_happy(tmp: Path) -> str:
    paths, recipe, task = start("debate", tmp / "run")
    out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    ks = kinds(paths)
    assert "halt" not in ks and "step.refused" not in ks
    verdicts = [e for e in events(paths) if e.kind == "judge.verdict"]
    assert verdicts and verdicts[0].data["verdict"] == "supported" and verdicts[0].data["total"] > 0
    rep = json.loads((paths.artifacts / "report" / "v001.json").read_text())
    assert "supported" in rep["verdict"] and (paths.run_dir / "evals.json").exists()
    keys = list(RunState.load(paths).steps)
    assert "p1-support" in keys and "p1-challenge" in keys and "p2-rebuttal" in keys and "p3-judge" in keys
    layers = assert_layers(paths, expect_tools=False)
    return f"{len(keys)} steps · {rep['verdict']} · {layers}"


def leg_debate_undecided_to_human(tmp: Path) -> str:
    with env(FAKE_VERDICT="checker:undecided"):
        paths, recipe, task = start("debate", tmp / "run", mode=Mode.LIGHT)
        out = make_runner(paths, recipe, task, gate_timeout=0.3).drive()
        assert out is Outcome.HALTED_HONESTLY and Halt.read(paths).step == "p0-gate-rubric", Halt.read(paths)
        gate = json.loads((paths.gates / "rubric.r1.ask.json").read_text())
        write_decision(
            paths,
            GateDecision(
                gate="rubric.r1",
                action="proceed",
                source="human",
                decisions=[
                    Decision(question_id=q["id"], answer=q["default"], answered_by="human")
                    for q in gate["questions"]
                ],
            ),
        )
        out = make_runner(paths, recipe, task, gate_timeout=0.3).drive()
        assert out is Outcome.HALTED_HONESTLY and Halt.read(paths).step == "p3-gate-verdict", Halt.read(paths)
        asked = [e for e in events(paths) if e.kind == "gate.asked" and e.data.get("gate") == "verdict.r1"]
        assert asked and asked[0].data["needs_human"] is True
        write_decision(
            paths,
            GateDecision(
                gate="verdict.r1",
                action="proceed",
                source="human",
                decisions=[Decision(question_id="Q-0001", answer="refuted", answered_by="human")],
            ),
        )
        out = make_runner(paths, recipe, task, gate_timeout=0.3).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    rep = json.loads((paths.artifacts / "report" / "v001.json").read_text())
    assert rep["verdict"].startswith("refuted") and any(c["kind"] == "ambiguity" for c in rep["carried"])
    return "judge undecided -> the human ruled refuted -> carried as an ambiguity"


def leg_debate_findings_rounds(tmp: Path) -> str:
    with env(FAKE_FINDINGS="checker:1:major"):
        paths, recipe, task = start("debate", tmp / "run", rounds=1)
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    assert any(e.kind == "finding.decided" for e in events(paths))
    return "one finding on the hypotheses, arbitrated, closing read"


def leg_gateway_drives_a_run(tmp: Path) -> str:
    """L2 (ARCHITECTURE.md 7.10): a run started, watched, paged and listed through the MCP
    gateway's in-memory client -- the same tools Claude Code and Codex call over stdio -- with
    the run executing detached under the Runner seam. The child inherits FAKE_MODELS, so no
    token is spent; the walk asserts on the record, never on the tool's words."""
    import asyncio
    import time

    from mcp import Client

    from .gateway.api import Gateway
    from .gateway.server import build
    from .layers.registry import RunRegistry

    gw = Gateway(registry=RunRegistry(tmp / "registry.db"))
    task = fake_task("debate", task_id="gw").model_dump(mode="json")

    async def drive() -> dict[str, Any]:
        async with Client(build(gw)) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            assert {
                "workflow_list",
                "workflow_run",
                "workflow_status",
                "workflow_cancel",
                "workflow_pause",
                "workflow_resume",
                "run_list",
                "run_get",
                "run_logs",
                "run_artifacts",
            } <= set(names), names
            wf = (await c.call_tool("workflow_list", {})).structured_content
            assert any(w["name"] == "debate" for w in wf["result"]), wf
            h = (
                await c.call_tool("workflow_run", {"task": task, "run_dir": str(tmp / "run")})
            ).structured_content
            assert h["status"] == "RUNNING" and h["pid"], h
            t0 = time.time()
            while True:
                st = (await c.call_tool("workflow_status", {"run": h["run_dir"]})).structured_content
                if st["status"] in ("COMPLETED", "FAILED", "PAUSED", "STALE"):
                    break
                assert time.time() - t0 < 120, f"the detached run did not finish: {st}"
                await asyncio.sleep(0.5)
            assert st["status"] == "COMPLETED" and st["verdict"], st
            page1 = (
                await c.call_tool("run_logs", {"run": h["run_dir"], "after": 0, "limit": 5})
            ).structured_content
            assert len(page1["events"]) == 5 and page1["more"] and page1["next_after"] == 5, page1
            page2 = (
                await c.call_tool(
                    "run_logs", {"run": h["run_dir"], "after": page1["next_after"], "limit": 1000}
                )
            ).structured_content
            assert page2["events"][0]["seq"] == 6 and not page2["more"], "paging by seq, never by position"
            arts = (await c.call_tool("run_artifacts", {"run": h["run_dir"]})).structured_content["result"]
            assert any(a["key"] == "report" for a in arts), arts
            runs = (await c.call_tool("run_list", {})).structured_content["result"]
            assert any(r["run_id"] == "gw" and r["status"] == "COMPLETED" for r in runs), runs
            # cancel and resume through the tools: a second run stopped at its next step boundary
            # (a halt that is a report), then continued at the first undone step
            task2 = dict(task, task_id="gw2")
            h2 = (
                await c.call_tool("workflow_run", {"task": task2, "run_dir": str(tmp / "run2")})
            ).structured_content
            await c.call_tool("workflow_cancel", {"run": h2["run_dir"]})
            t0 = time.time()
            while True:
                s2 = (await c.call_tool("workflow_status", {"run": h2["run_dir"]})).structured_content
                if s2["status"] in ("PAUSED", "COMPLETED", "FAILED", "STALE"):
                    break
                assert time.time() - t0 < 120, s2
                await asyncio.sleep(0.3)
            if s2["status"] == "PAUSED":
                assert s2["halt"] and "cancel" in s2["halt"], s2
                await c.call_tool("workflow_resume", {"run": h2["run_dir"]})
                t0 = time.time()
                while True:
                    s3 = (await c.call_tool("workflow_status", {"run": h2["run_dir"]})).structured_content
                    if s3["status"] in ("COMPLETED", "FAILED", "STALE"):
                        break
                    assert time.time() - t0 < 120, s3
                    await asyncio.sleep(0.3)
                assert s3["status"] == "COMPLETED" and s3["resumed"] == 1, s3
                st["cancelled_then_resumed"] = True
            else:
                st["cancelled_then_resumed"] = (
                    False  # the run outran the cancel; the tool still answered honestly
                )
            return st

    st = asyncio.run(drive())
    cr = (
        "cancelled at a step boundary and resumed once"
        if st.get("cancelled_then_resumed")
        else "the second run outran the cancel"
    )
    return f"run through the gateway: {st['steps_done']}/{st['steps_total']} steps · {st['verdict']} · logs paged by seq · {cr}"


def leg_budget_halts_then_resumes(tmp: Path) -> str:
    """P1 (ARCHITECTURE.md section 5): a role's token ceiling is checked before a step is issued;
    over it the run halts honestly and resumably; raised, it resumes at the first undone step."""
    paths, recipe, task = start("debate", tmp / "run")
    st = RunState.load(paths)
    roles = {
        r: s.model_copy(update={"budget_tokens": 1}) if r == "author" else s for r, s in st.task.roles.items()
    }
    st.task = st.task.model_copy(update={"roles": roles})
    st.save(paths)
    out = make_runner(paths, recipe, st.task).drive()
    h = Halt.read(paths)
    assert out is Outcome.HALTED_HONESTLY and h is not None and h.reason.value == "budget" and h.resumable, (
        out,
        h,
    )
    assert "author spent" in h.message and "ceiling" in h.message, h.message
    st = RunState.load(paths)
    roles = {r: s.model_copy(update={"budget_tokens": None}) for r, s in st.task.roles.items()}
    st.task = st.task.model_copy(update={"roles": roles})
    st.save(paths)
    out2 = make_runner(paths, recipe, st.task).drive()
    assert out2 is Outcome.COMPLETED, Halt.read(paths)
    assert RunState.load(paths).resumed_count == 1
    return f"halted at {h.step} on the ceiling, resumed once the ceiling was lifted, completed"


LEGS: dict[str, dict[str, Leg]] = {
    "gateway": {
        "drives-a-run": leg_gateway_drives_a_run,
        "budget-halts-then-resumes": leg_budget_halts_then_resumes,
    },
    "debate": {
        "happy": leg_debate_happy,
        "undecided-to-human": leg_debate_undecided_to_human,
        "findings-rounds": leg_debate_findings_rounds,
    },
    "code_builder": {
        "happy": leg_happy,
        "refuse-recover": leg_refuse_recover,
        "no-progress-halt-resume": leg_no_progress_halts_then_resume,
        "findings-rounds-closing": leg_findings_rounds_and_closing,
        "closing-carries": leg_closing_carries,
        "buggy-impl-triage-fix": leg_buggy_impl_triage_fix,
        "test-bug-route": leg_test_bug_route,
        "ambiguity-carried": leg_ambiguity_carried,
        "gate-revise": leg_gate_revise,
        "light-mode-human": leg_light_mode_waits_then_human,
    },
}


def run(recipe: str = "all", *, only: str | None = None, keep: bool = False) -> list[LegResult]:
    legs = {**LEGS, **registry.walk_legs()}  # bundled legs, then the installed recipes' own
    names = list(legs) if recipe == "all" else [recipe]
    results: list[LegResult] = []
    for rn in names:
        for leg_name, fn in legs[rn].items():
            if only and leg_name != only:
                continue
            tmp = Path(tempfile.mkdtemp(prefix=f"csmw-walk-{rn}-{leg_name}-"))
            t0 = time.time()
            with env(FAKE_MODELS="1"):
                try:
                    detail = fn(tmp)
                    results.append(
                        LegResult(
                            name=f"{rn}/{leg_name}",
                            ok=True,
                            outcome="ok",
                            seconds=round(time.time() - t0, 2),
                            detail=detail,
                            run_dir=str(tmp),
                        )
                    )
                except AssertionError as e:
                    results.append(
                        LegResult(
                            name=f"{rn}/{leg_name}",
                            ok=False,
                            outcome="assert",
                            seconds=round(time.time() - t0, 2),
                            detail=str(e)[:600],
                            run_dir=str(tmp),
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    results.append(
                        LegResult(
                            name=f"{rn}/{leg_name}",
                            ok=False,
                            outcome="broke",
                            seconds=round(time.time() - t0, 2),
                            detail=f"{type(e).__name__}: {e}"[:600],
                            run_dir=str(tmp),
                        )
                    )
            if not keep and results[-1].ok:
                shutil.rmtree(tmp, ignore_errors=True)
    return results


def report(results: list[LegResult]) -> str:
    lines = []
    for r in results:
        mark = "ok  " if r.ok else "FAIL"
        lines.append(
            f"{mark} {r.name:40s} {r.seconds:6.1f}s  {r.detail}"
            + ("" if r.ok else f"\n       run dir: {r.run_dir}")
        )
    n_ok = sum(1 for r in results if r.ok)
    lines.append(f"walk: {n_ok}/{len(results)} legs ok")
    return "\n".join(lines)
