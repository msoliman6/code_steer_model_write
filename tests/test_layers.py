"""The seams (ARCHITECTURE.md section 6): each interface's first implementation behaves, and
every decision, verdict, tool call and execution is an event (section 2, invariant 5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from code_steer_model_write.events import EventLog
from code_steer_model_write.layers import Layers, current, default_layers, install
from code_steer_model_write.layers.policy import Principal, RunIdentity, StepPolicy
from code_steer_model_write.layers.rails import SchemaRails
from code_steer_model_write.layers.sandbox import Execution, SubprocessSandbox
from code_steer_model_write.layers.stores import ArtifactStore, NoMemory, StateStore
from code_steer_model_write.layers.tools import Tool, ToolSpec, default_registry
from code_steer_model_write.artifacts.store import Store


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "events.jsonl", "run_t")


def kinds(log: EventLog) -> list[str]:
    return [e.kind for e in log.read()]


# ---- L9 -----------------------------------------------------------------------------------


def test_policy_decides_deterministically_and_logs(log: EventLog) -> None:
    pol = StepPolicy(events=log)
    a = Principal(id="side:author", kind="side")
    assert pol.decide(a, "author", "plan")
    assert not pol.decide(a, "judge", "plan", {"author": "side:author"}), "an author judged its own work"
    assert pol.decide(Principal(id="side:checker", kind="side"), "judge", "plan", {"author": "side:author"})
    assert not pol.decide(a, "tool", "shell", {"declared": []}), "default deny did not hold"
    assert pol.decide(a, "tool", "shell", {"declared": ["shell"]})
    assert not pol.decide(a, "write", "tests/x.py", {"allowed": ["src/x.py"]})
    assert pol.decide(a, "write", "src/x.py", {"allowed": ["src/x.py"]})
    assert pol.decide(a, "execute", "p3", {"root": "/r", "cwd": "/r/build"})
    assert not pol.decide(a, "execute", "p3", {"root": "/r", "cwd": "/elsewhere"})
    human = Principal(id="user:me", kind="human")
    assert pol.decide(human, "gate", "blocks.r1")
    assert not pol.decide(a, "gate", "blocks.r1", {"auto_allowed": False})
    evs = [e for e in log.read() if e.kind == "policy.decision"]
    assert len(evs) == 11 and all(e.data["policy"].startswith("P-") for e in evs)
    ids = [e.data["decision"] for e in evs]
    assert ids == sorted(ids) and len(set(ids)) == len(ids), "decision ids are code-assigned and unique"


def test_identity_is_minted_from_the_runspec(tmp_path: Path) -> None:
    ident = RunIdentity(None)
    assert ident.side("author").id == "side:author"
    assert ident.user().kind == "human" and ident.tool("git").kind == "tool"


# ---- L10 ----------------------------------------------------------------------------------


def test_rails_accept_or_refuse_and_never_rewrite(log: EventLog) -> None:
    from code_steer_model_write.spec.base import Artifact, CheckContext, Problem

    class Note(Artifact):
        title: str
        body: str

        def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
            return [] if self.title else [Problem(code="empty_title", message="a note needs a title")]

    rails = SchemaRails(events=log)
    assert rails.before_prompt("system\nuser", step="s1", role="author")
    good = Note(title="ok", body="fine")
    v = rails.after_answer(good, CheckContext(), step="s1", role="author")
    assert v and v.problems == []
    bad = Note(title="", body="fine")
    v2 = rails.after_answer(bad, CheckContext(), step="s1", role="author")
    assert not v2 and v2.problems, "a refusal carries its problems"
    assert bad.title == "", "a rail never rewrites the answer"
    hooks = [e.data["hook"] for e in log.read() if e.kind == "rail.verdict"]
    assert hooks == ["before_prompt", "after_answer", "after_answer"]


# ---- L5 -----------------------------------------------------------------------------------


def test_subprocess_sandbox_reports_exit_output_and_files_touched(tmp_path: Path, log: EventLog) -> None:
    sb = SubprocessSandbox(events=log)
    r = sb.run(
        Execution(
            command=[sys.executable, "-c", "open('out.txt','w').write('x'); print('hi')"], root=tmp_path
        )
    )
    assert (
        r.exit_code == 0 and r.stdout.strip() == "hi" and r.touched == ["out.txt"] and r.tier == "subprocess"
    )
    r2 = sb.run(
        Execution(command=[sys.executable, "-c", "import time; time.sleep(5)"], root=tmp_path, timeout=0.5)
    )
    assert r2.timed_out and r2.exit_code == 124
    runs = [e for e in log.read() if e.kind == "sandbox.run"]
    assert len(runs) == 2 and runs[0].data["touched"] == 1 and runs[1].data["timed_out"]


# ---- L6 -----------------------------------------------------------------------------------


def test_registry_logs_before_and_after_and_runs_in_the_sandbox(tmp_path: Path, log: EventLog) -> None:
    reg = default_registry(SubprocessSandbox(events=log), events=log)
    assert reg.names() == ["git", "pyright", "pytest", "ruff"]
    reg.register(
        Tool(
            spec=ToolSpec(name="echo", description="say it", args_schema={"text": "str"}, timeout=5),
            build=lambda a: Execution(command=["echo", a["text"]], root=tmp_path),
        )
    )
    r = reg.invoke("echo", {"text": "hello"}, step="s1")
    assert r.exit_code == 0 and r.stdout.strip() == "hello"
    ks = kinds(log)
    assert ks == ["tool.called", "sandbox.run", "tool.result"], ks
    called, result = [e for e in log.read() if e.kind in ("tool.called", "tool.result")]
    assert called.data["gen_ai.tool.name"] == "echo" == result.data["gen_ai.tool.name"]
    assert called.data["gen_ai.tool.call.id"] == result.data["gen_ai.tool.call.id"]
    with pytest.raises(KeyError):
        reg.get("shell")


# ---- L7 -----------------------------------------------------------------------------------


def test_the_existing_stores_satisfy_the_seams(tmp_path: Path, log: EventLog) -> None:
    assert isinstance(log, StateStore)
    assert isinstance(Store(tmp_path), ArtifactStore)
    with pytest.raises(RuntimeError):
        NoMemory().query("anything")


# ---- the set ------------------------------------------------------------------------------


def test_default_layers_install_and_are_current(tmp_path: Path, log: EventLog) -> None:
    layers = install(default_layers(None, log))
    assert isinstance(layers, Layers) and current() is layers
    assert current().tools.names() == ["git", "pyright", "pytest", "ruff"]
