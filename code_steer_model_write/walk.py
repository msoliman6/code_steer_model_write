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
from .layers import default_layers
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
    # paired by call id, never by order: parallel steps interleave their tool events
    by_id = {r.data["gen_ai.tool.call.id"] for r in results}
    for c in called:
        assert c.data["gen_ai.tool.call.id"] in by_id, f"a call with no result: {c.data['gen_ai.tool.name']}"
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
            # §7d: run again carries the task unchanged; forget stops the listing, keeps the folder
            h3 = (await c.call_tool("workflow_run_again", {"run": h["run_dir"]})).structured_content
            assert h3["run_dir"] != h["run_dir"] and h3["run_id"].startswith("gw"), h3
            t_a = json.loads((Path(h["run_dir"]) / "task.json").read_text())
            t_b = json.loads((Path(h3["run_dir"]) / "task.json").read_text())
            assert {k for k in t_a if t_a[k] != t_b.get(k)} <= {"task_id"}, (
                "run again changed more than the id"
            )
            await c.call_tool("workflow_cancel", {"run": h3["run_dir"]})
            gone = (await c.call_tool("run_forget", {"run": h2["run_dir"]})).structured_content["result"]
            runs = (await c.call_tool("run_list", {})).structured_content["result"]
            assert Path(gone, "state.json").exists() and all(r["run_dir"] != gone for r in runs), runs
            st["again"] = h3["run_id"]
            return st

    st = asyncio.run(drive())
    # the home page reads the same registry through the same reader the page uses (§7d); the
    # page is the runtime repo's own package, so a walk from a project venv skips this and says so
    try:
        from dashboard import home as _home
    except ImportError:
        home_note = "home reader not installed here"
    else:
        rows = _home.rows(gw.registry)
        mine = [r for r in rows if r.dir == str((tmp / "run").resolve())]  # the registry's form
        assert mine and mine[0].bucket == "completed" and mine[0].verdict == st["verdict"], [
            r.dir for r in rows
        ]
        assert mine[0].steps_done == st["steps_done"] and mine[0].eval_values, mine[0]
        assert _home.counters(rows)["all"] == len(rows) and str((tmp / "run2").resolve()) not in {
            r.dir for r in rows
        }
        home_note = "listed on the home"
    cr = (
        "cancelled at a step boundary and resumed once"
        if st.get("cancelled_then_resumed")
        else "the second run outran the cancel"
    )
    return f"run through the gateway: {st['steps_done']}/{st['steps_total']} steps · {st['verdict']} · logs paged by seq · {cr} · {st['again']} run again · gw2 forgotten · {home_note}"


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


def leg_parallel_steps_overlap(tmp: Path) -> str:
    """L3 (ARCHITECTURE.md 7.3): independent ready steps run at once. The debate's support and
    challenge steps depend only on the hypotheses, so their records must overlap in time, and
    both must land whole under the locked state update (ledger: a shared record written by
    parallel workers). The fake backend sleeps a little so overlap is measurable."""
    with env(FAKE_SLEEP="0.6"):
        paths, recipe, task = start("debate", tmp / "run")
        out = make_runner(paths, recipe, task).drive()
    assert out is Outcome.COMPLETED, Halt.read(paths)
    st = RunState.load(paths)
    a, b = st.steps["p1-support"], st.steps["p1-challenge"]
    assert a.started_at and a.done_at and b.started_at and b.done_at, "both records landed whole"
    overlap = min(a.done_at, b.done_at) > max(a.started_at, b.started_at)
    assert overlap, (
        f"the two steps ran one after the other: {a.started_at}..{a.done_at} / {b.started_at}..{b.done_at}"
    )
    par = [e for e in events(paths) if e.kind == "run.progress" and "parallel" in e.data]
    assert par and set(par[0].data["parallel"]) >= {"p1-support", "p1-challenge"}, par
    ks = kinds(paths)
    assert ks.count("step.started") == len(st.steps) and "halt" not in ks
    return f"support ‖ challenge overlapped by {(min(a.done_at, b.done_at) - max(a.started_at, b.started_at)).total_seconds():.2f}s; every record whole"


def leg_container_tier(tmp: Path) -> str:
    """L5's container tier (phase 8): when an engine and the image are here, one pytest run of
    the coder's own fake build executes in a container, network off, the run folder the only
    mount, and the record says `tier=container`; without an engine the leg says so and passes,
    since the walk is zero-setup and the fallback is itself a recorded fact."""
    from .layers import container_sandbox

    ok, why = container_sandbox.available()
    if not ok:
        return f"skipped: {why}"
    home = Path.home()
    root = tmp if tmp.resolve().is_relative_to(home) else home / ".csmw" / f"walk-{tmp.name}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        (root / "m.py").write_text("def f():\n    return 1\n")
        (root / "test_m.py").write_text("from m import f\n\n\ndef test_f():\n    assert f() == 1\n")
        paths = RunPaths(run_dir=root)
        log = EventLog(paths.events, "walk-container")
        with env(CSMW_SANDBOX="container"):
            layers = default_layers(paths, log)
        assert layers.sandbox.tier == "container", layers.installed()
        r = layers.tools.invoke(
            "pytest", {"tests_dir": root, "src_dir": root, "junit": root / "junit.xml", "timeout": 120}
        )
        assert r.exit_code == 0 and r.tier == "container" and (root / "junit.xml").exists(), (
            r.exit_code,
            r.stderr[-300:],
        )
        ev = [e for e in log.read() if e.kind == "sandbox.run"]
        assert ev and ev[-1].data["tier"] == "container" and ev[-1].data["network"] is True
        return f"pytest in a container ({why}), the run folder the only mount, {r.seconds}s"
    finally:
        if root != tmp:
            import shutil

            shutil.rmtree(root, ignore_errors=True)


def leg_tool_using_step(tmp: Path) -> str:
    """The tool-using step kind (phase 9, across L4, L6 and L5): a program declares a tool of
    its own and a TOOL step that may call it; the model (the fake) calls it once through the
    callback; every call goes L9 decide -> L10 before_tool_call -> L6 registry -> L5 sandbox,
    and the answer still lands under its schema. A second program declares a tool outside the
    profile's allowance (P8) and never starts."""
    from pydantic import Field

    from .layers.profile import Profile
    from .layers.sandbox import Execution
    from .layers.tools import Tool, ToolSpec, _schema
    from .prompts import PROMPTS_DIR  # noqa: F401 -- the templates live beside the package
    from .spec.base import Artifact

    class Note(Artifact):
        text: str = Field(min_length=3)
        bytes_seen: int = Field(ge=0)

    run_dir = tmp / "run"
    prompts = tmp / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "count.md").write_text(
        "You may call the `wc` tool on a file under the run folder, then answer ONE JSON object "
        "matching the `Note` schema; code writes the file.\n\n{{BRIEF_MD}}\n"
    )
    run_dir.mkdir(parents=True)
    (run_dir / "notes.txt").write_text("hello walk\n")

    def _wc(args: dict[str, Any]) -> Execution:
        return Execution(command=["wc", "-c", str(run_dir / args["file"])], root=run_dir, timeout=30)

    wc = Tool(
        spec=ToolSpec(
            name="wc",
            description="count the bytes of a file under the run folder",
            args_schema=_schema({"file": {"type": "string"}}, ["file"], examples=[{"file": "notes.txt"}]),
            permissions=["read"],
            timeout=30,
            binary="wc",
        ),
        build=_wc,
    )

    class ToolProgram:
        name = "walk-tools"
        prompts_root = prompts
        fixtures_root = None
        schemas = {"Note": Note}
        code_steps: dict[str, Any] = {}
        checks: dict[str, Any] = {}
        tools = [wc]
        profile = Profile(name="walk-tools", tools_allowed=["wc"], policy_engine="cedar")

        def __init__(self, declared: list[str]) -> None:
            self.declared = declared

        def steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Any]:
            from .driver.steps import Step, StepKind

            return [
                Step(
                    key="p0-count",
                    kind=StepKind.TOOL,
                    phase="0",
                    prompt="count",
                    schema_name="Note",
                    role="author",
                    sets={"BRIEF_MD": "## Brief\n\n- count notes.txt\n"},
                    rendered_keys=["brief"],
                    land="note",
                    tools=self.declared,
                    deliverables=["artifacts/note/v001.json"],
                    note="the model counts with a tool",
                )
            ]

        def land(self, step: Any, value: Any, ctx: Any) -> list[str]:
            v = ctx.store.write(step.land, value)
            return [f"artifacts/{step.land}/v{v:03d}.json"]

        def gate_builders(self) -> dict[str, Any]:
            return {}

        def fakers(self, paths: RunPaths, store: Store) -> dict[str, Any]:
            return {"Note": lambda call: {"text": "counted", "bytes_seen": 11}}

    task = fake_task("debate")
    RunState.create(RunPaths(run_dir=run_dir), task)
    paths = RunPaths(run_dir=run_dir)
    prog = ToolProgram(["wc"])
    fake = FakeBackend(fixtures_root=None, fakers=prog.fakers(paths, Store(run_dir)))
    runner = Runner(paths, prog, {"fake": fake}, task.roles, make_waiter(task.mode, {}), poll_seconds=0.02)  # type: ignore[arg-type]
    out = runner.drive()
    ev = events(paths)
    assert out is Outcome.COMPLETED, (out, Halt.read(paths))
    dec = [e for e in ev if e.kind == "policy.decision" and e.data.get("action") == "tool"]
    assert dec and dec[0].data["allow"] and dec[0].data["resource"] == "wc", dec
    ver = [e for e in ev if e.kind == "rail.verdict" and e.data.get("hook") == "before_tool_call"]
    assert ver and ver[0].data["accept"] and ver[0].data["rail"] == "toolspec", ver
    called = [e for e in ev if e.kind == "tool.called" and e.data["gen_ai.tool.name"] == "wc"]
    res = [e for e in ev if e.kind == "tool.result" and e.data["gen_ai.tool.name"] == "wc"]
    sbx = [e for e in ev if e.kind == "sandbox.run" and e.data.get("tool") == "wc"]
    assert len(called) == 1 and len(res) == 1 and res[0].data["exit_code"] == 0 and len(sbx) == 1, (
        called,
        res,
    )
    order = [
        e.kind
        for e in ev
        if e.kind
        in ("policy.decision", "rail.verdict", "tool.called", "sandbox.run", "tool.result", "call.final")
    ]
    i = order.index("tool.called")
    assert order[i - 2 : i + 3] == [
        "policy.decision",
        "rail.verdict",
        "tool.called",
        "sandbox.run",
        "tool.result",
    ], order
    note = Store(run_dir).read("note", Note)
    assert note.bytes_seen == 11
    # P8: a step outside the allowance never starts
    run2 = tmp / "run2"
    run2.mkdir()
    RunState.create(RunPaths(run_dir=run2), task)
    prog2 = ToolProgram(["wc", "git"])
    runner2 = Runner(
        RunPaths(run_dir=run2),
        prog2,
        {"fake": fake},
        task.roles,
        make_waiter(task.mode, {}),
        poll_seconds=0.02,
    )  # type: ignore[arg-type]
    out2 = runner2.drive()
    h = Halt.read(RunPaths(run_dir=run2))
    assert out2 is Outcome.BROKE and h is not None and "outside the profile's allowance" in h.message, (
        out2,
        h,
    )
    return "wc called once: L9 allow · L10 toolspec · L6 · L5 subprocess · the answer landed under Note; a step declaring git outside P8 never started"


LEGS: dict[str, dict[str, Leg]] = {
    "gateway": {
        "tool-using-step": leg_tool_using_step,
        "container-tier": leg_container_tier,
        "parallel-steps-overlap": leg_parallel_steps_overlap,
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
            # the container tier can only see what the engine shares (Colima: the home
            # directory), so a walk under it keeps its run folders under ~/.csmw/walk
            base = None
            if os.environ.get("CSMW_SANDBOX") == "container":
                base = Path.home() / ".csmw" / "walk"
                base.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=f"csmw-walk-{rn}-{leg_name}-", dir=base))
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
