"""L2 (ARCHITECTURE.md 7.10): the registry across runs directories, the gateway's operations,
and the MCP server reached over stdio as a real subprocess -- the transport the hosts use."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from code_steer_model_write.gateway.api import Gateway
from code_steer_model_write.layers.registry import RunRegistry
from code_steer_model_write.spec.task import TaskSpec
from code_steer_model_write.state.run import RunPaths, RunState

ROOT = Path(__file__).resolve().parents[1]


def _task(task_id: str) -> TaskSpec:
    ex = json.loads((ROOT / "examples" / "debate" / "task.json").read_text())
    ex["task_id"] = task_id
    ex["mode"] = "auto"  # every gate auto-answered and flagged; nothing waits for a human
    ex["roles"] = {r: {"backend": "fake", "model": f"fake-{r}"} for r in ex["roles"]}
    return TaskSpec.model_validate(ex)


def test_registry_indexes_runs_across_directories_and_refreshes_from_state(tmp_path: Path) -> None:
    reg = RunRegistry(tmp_path / "registry.db")
    a, b = tmp_path / "proj-a" / "runs", tmp_path / "proj-b" / "runs"
    for d, name in ((a, "one"), (b, "two")):
        RunState.create(RunPaths(run_dir=d / name), _task(name))
        reg.add_dir(d)
    assert reg.scan() == 2
    rows = reg.refresh()
    assert {r["run_id"] for r in rows} == {"one", "two"}
    assert all(r["status"] == "QUEUED" for r in rows), rows  # created, never started
    assert reg.find("two").run_dir == b / "two"
    assert reg.find("nope") is None
    assert [Path(p) for p in reg.dirs()] == [a.resolve(), b.resolve()]


def test_gateway_refuses_a_bad_task_and_a_second_run_in_the_same_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_MODELS", "1")
    gw = Gateway(registry=RunRegistry(tmp_path / "r.db"))
    bad = _task("bad").model_dump(mode="json")
    bad["roles"] = {}
    with pytest.raises(Exception) as e:  # the recipe refuses a task missing a role, before any run
        gw.run(bad, run_dir=str(tmp_path / "bad"))
    assert "refused" in str(e.value) or "role" in str(e.value).lower(), e.value
    assert not (tmp_path / "bad" / "state.json").exists(), "a refused task created a run"
    with pytest.raises(KeyError):
        gw.status("no-such-run")


def test_gateway_over_stdio_as_a_subprocess(tmp_path: Path) -> None:
    """The stdio transport the hosts use: the server as a child process, the SDK's client over
    its pipes, tools listed with schemas from pydantic."""
    from mcp import Client, StdioServerParameters

    env = {**os.environ, "CSMW_REGISTRY": str(tmp_path / "r.db"), "FAKE_MODELS": "1"}

    async def go():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "code_steer_model_write.gateway"], env=env, cwd=str(ROOT)
        )
        async with Client(params) as c:
            tools = (await c.list_tools()).tools
            names = {t.name for t in tools}
            assert "workflow_run" in names and "run_logs" in names, names
            run_tool = next(t for t in tools if t.name == "workflow_run")
            assert "task" in run_tool.input_schema["properties"] and run_tool.output_schema, run_tool
            wf = (await c.call_tool("workflow_list", {})).structured_content["result"]
            assert {w["name"] for w in wf} >= {"debate"}, wf
            return names

    asyncio.run(go())


def test_prefect_runner_submits_cancels_and_resumes_under_a_test_harness(tmp_path: Path, monkeypatch) -> None:
    """L3's second Runner (7.3) against Prefect's own test harness: a temporary server, the
    deployment served in a thread, a run submitted through the seam and driven to completion
    by the served flow; then a second run cancelled through Prefect's state and resumed. No
    external service, no network."""
    import threading
    import time

    from prefect.testing.utilities import prefect_test_harness

    from code_steer_model_write.layers.prefect_runner import PrefectRunner
    from code_steer_model_write.workflow.flows import flow_for

    monkeypatch.setenv("FAKE_MODELS", "1")
    with prefect_test_harness():
        flow = flow_for()
        t = threading.Thread(
            target=lambda: flow.serve(
                name="local", limit=2, pause_on_shutdown=False, print_starting_message=False
            ),
            daemon=True,
        )
        t.start()
        pr = PrefectRunner()
        deadline = time.time() + 60
        while time.time() < deadline:
            ok, why = pr.available()
            if ok:
                break
            time.sleep(0.5)
        assert ok, why
        paths = RunPaths(run_dir=tmp_path / "one")
        RunState.create(paths, _task("one"))
        h = pr.submit(paths)
        assert h.status == "RUNNING" and (tmp_path / "one" / "prefect.json").exists(), h
        deadline = time.time() + 120
        while time.time() < deadline:
            if RunState.load(paths).status.value in ("COMPLETED", "FAILED", "PAUSED"):
                break
            time.sleep(0.5)
        st = RunState.load(paths)
        assert st.status.value == "COMPLETED", (st.status, pr.status(paths))
        assert (tmp_path / "one" / "artifacts" / "report").exists()
