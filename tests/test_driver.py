import json

import pytest

from code_steer_model_write.backends.fake import FakeBackend, register_faker
from code_steer_model_write.config import BackendName, Mode, RoleSpec
from code_steer_model_write.driver.driver import Driver, DriverError
from code_steer_model_write.driver.halt import Halt, HaltReason
from code_steer_model_write.driver.runner import Runner
from code_steer_model_write.events import EventLog
from code_steer_model_write.spec.task import TaskSpec
from code_steer_model_write.state.run import Outcome, RunPaths, RunState, RunStatus
from tests.toy_program import ToyProgram


def _task():
    return TaskSpec(
        task_id="t1",
        objective="slug",
        recipe="toy",
        mode=Mode.AUTO,
        roles={
            "author": RoleSpec(backend=BackendName.FAKE, model="fake-a"),
            "checker": RoleSpec(backend=BackendName.FAKE, model="fake-b"),
        },
        swaps=[("author", "checker")],
    )


def _gate_auto(step, ctx):
    p = ctx.paths.gates / f"{step.gate}.decision.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"action": "proceed", "source": "auto", "flagged": ["blocks"]}))
        ctx.events.append("gate.decided", step=step.key, source="auto")
    return True


def _gate_never(step, ctx):
    return (ctx.paths.gates / f"{step.gate}.decision.json").exists()


@pytest.fixture(autouse=True)
def _faker():
    register_faker(
        "Plan", lambda call: {"blocks": ["slug"], "summary": "one block, the slug function, nothing else"}
    )


def _runner(tmp_path, program=None, waiter=_gate_auto, **kw):
    paths = RunPaths(run_dir=tmp_path / "run")
    RunState.create(paths, _task())
    prog = program or ToyProgram()
    roles = _task().roles
    return Runner(paths, prog, {"fake": FakeBackend()}, roles, waiter, poll_seconds=0.01, **kw), paths


def test_task_spec_refuses_self_check_and_same_vendor():
    with pytest.raises(ValueError, match="rule 3"):
        TaskSpec(
            task_id="t",
            objective="o",
            recipe="r",
            roles={"a": RoleSpec(backend=BackendName.ANTHROPIC, model="x")},
            swaps=[("a", "a")],
        )
    with pytest.raises(ValueError, match="same vendor"):
        TaskSpec(
            task_id="t",
            objective="o",
            recipe="r",
            roles={
                "a": RoleSpec(backend=BackendName.ANTHROPIC, model="x"),
                "b": RoleSpec(backend=BackendName.CLAUDE_CLI, model="y"),
            },
            swaps=[("a", "b")],
        )


def test_full_drive_completes_with_honest_records(tmp_path):
    runner, paths = _runner(tmp_path)
    assert runner.drive() is Outcome.COMPLETED
    st = RunState.load(paths)
    assert st.status is RunStatus.COMPLETED and st.completed_at is not None
    assert set(st.done_keys()) == {"p0-plan", "p0-freeze", "p0-check", "p0-gate", "p1-run"}
    assert (paths.run_dir / "out.txt").read_text() == "ok"
    assert json.loads((paths.run_dir / "freeze.json").read_text())["plan_sha"]
    kinds = [e.kind for e in EventLog(paths.events, "t1").all()]
    assert kinds.count("artifact.written") == 2 and "gate.decided" in kinds and kinds[-1] == "run.status"
    # steps are issued only once each and in data order
    issued = [e.data.get("phase") for e in EventLog(paths.events, "t1").all() if e.kind == "step.issued"]
    assert issued == ["0", "0", "0", "0", "1"]


def test_refusal_halts_as_report_and_resume_continues(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REFUSE", "author:same")
    runner, paths = _runner(tmp_path)
    assert runner.drive() is Outcome.HALTED_HONESTLY
    h = Halt.read(paths)
    assert h and h.step == "p0-plan" and h.reason is HaltReason.REFUSED and "same problems" in h.message
    assert RunState.load(paths).status is RunStatus.PAUSED
    monkeypatch.delenv("FAKE_REFUSE")
    runner2 = Runner(
        paths, ToyProgram(), {"fake": FakeBackend()}, _task().roles, _gate_auto, poll_seconds=0.01
    )
    assert runner2.drive() is Outcome.COMPLETED
    st = RunState.load(paths)
    assert st.resumed_count == 1 and st.last_halt.startswith("HALT at p0-plan") and Halt.read(paths) is None


def test_run_step_failure_carries_the_last_lines(tmp_path):
    prog = ToyProgram(run_cmd=["python3", "-c", "import sys; print('boom line'); sys.exit(3)"])
    runner, paths = _runner(tmp_path, prog)
    assert runner.drive() is Outcome.HALTED_HONESTLY
    h = Halt.read(paths)
    assert (
        h.reason is HaltReason.RUN_FAILED and h.command[0] == "python3" and h.facts[-1]["line"] == "boom line"
    )


def test_check_problems_halt_by_policy(tmp_path):
    runner, paths = _runner(tmp_path, ToyProgram(check_problems=["plan.blocks: no boundary stated"]))
    assert runner.drive() is Outcome.HALTED_HONESTLY
    assert Halt.read(paths).reason is HaltReason.CHECK_FAILED


def test_gate_blocks_until_decision_file(tmp_path):
    runner, paths = _runner(tmp_path, waiter=_gate_never, gate_timeout=0.05)
    assert runner.drive() is Outcome.HALTED_HONESTLY
    assert Halt.read(paths).reason is HaltReason.CANCELLED
    # a human writes the decision; resume continues from the gate
    paths.gates.mkdir(exist_ok=True)
    (paths.gates / "blocks.decision.json").write_text('{"action":"proceed","source":"human"}')
    r2 = Runner(
        paths,
        ToyProgram(),
        {"fake": FakeBackend()},
        _task().roles,
        _gate_never,
        poll_seconds=0.01,
        gate_timeout=0.05,
    )
    assert r2.drive() is Outcome.COMPLETED


def test_missing_deliverable_reopens_and_undo_moves_aside(tmp_path):
    runner, paths = _runner(tmp_path)
    runner.drive()
    (paths.run_dir / "out.txt").unlink()  # state left by an earlier step, gone
    d = Driver(paths, ToyProgram())
    ready = d.next()
    assert [s.key for s in ready] == ["p1-run"]
    assert RunState.load(paths).steps["p1-run"].done_at is None
    with pytest.raises(DriverError, match="missing"):
        d.done("p1-run")
    d.undo("p0-freeze")
    assert not (paths.run_dir / "freeze.json").exists()
    assert list(paths.undone.rglob("freeze.json"))
    assert "p0-freeze" not in RunState.load(paths).steps
    # `after` is direct: the undone freeze is ready again, and so is the reopened run step
    assert {s.key for s in d.next()} == {"p0-freeze", "p1-run"}


def test_second_run_in_same_dir_refused(tmp_path):
    paths = RunPaths(run_dir=tmp_path / "run")
    RunState.create(paths, _task())
    with pytest.raises(FileExistsError):
        RunState.create(paths, _task())
