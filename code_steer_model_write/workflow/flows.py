"""Prefect around the driver (ARCHITECTURE.md 7.3): Prefect is the Runner -- detached runs,
cancellation through its state, parallel steps as task runs, a UI -- and never the Driver.
`state.json` stays the record; Prefect's flow-run state is a view the run never reads back.

Two entry points. `csmw_run(run_dir)` is the deployment's flow: the driver's own loop, the
whole run in one flow run, with a cancellation hook that writes the halt. `drive_with_prefect`
is the older per-step form (`--prefect`): every ready step a task run, independent ones
submitted together, so tests ‖ source are two task runs side by side."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect import flow as _flow

from ..driver.halt import Halt, HaltReason
from ..driver.runner import Runner
from ..state.run import Outcome
from .names import DEPLOYMENT, FLOW_NAME


def _cancel_hook(paths):
    def on_cancel(flow: Any, flow_run: Any, state: Any) -> None:
        Halt(
            step="prefect", reason=HaltReason.CANCELLED, message="cancelled through Prefect", resumable=True
        ).write(paths)

    return on_cancel


def drive_with_prefect(runner: Runner, *, flow_name: str | None = None) -> Outcome:
    from prefect import flow, task

    @task(name="step", retries=0)
    def step_task(key: str) -> str | None:
        step = next(s for s in runner.driver.next() if s.key == key)
        out = runner._execute(step)
        return out.value if out is not None else None

    def on_cancel(flow: Any, flow_run: Any, state: Any) -> None:
        runner._halt(
            Halt(
                step="prefect", reason=HaltReason.CANCELLED, message="cancelled from Prefect", resumable=True
            )
        )

    @flow(
        name=flow_name or f"csmw:{runner.driver.state.run_id}", on_cancellation=[on_cancel], log_prints=True
    )
    def drive_flow() -> str:
        outcome = runner.begin()
        if outcome is not None:
            return outcome.value
        while True:
            ready = runner.driver.next()
            if not ready:
                return runner.finish().value
            # independent ready steps as task runs side by side (7.3); a halt in any ends the round
            futures = [step_task.with_options(task_run_name=s.key).submit(s.key) for s in ready]
            results = [f.result() for f in futures]
            hit = next((r for r in results if r is not None), None)
            if hit is not None:
                return hit

    return Outcome(drive_flow())


def _on_cancel(flow: Any, flow_run: Any, state: Any) -> None:
    run_dir = (flow_run.parameters or {}).get("run_dir")
    if run_dir:
        from ..state.run import RunPaths

        _cancel_hook(RunPaths(run_dir=Path(run_dir)))(flow, flow_run, state)


@_flow(name=FLOW_NAME, on_cancellation=[_on_cancel], log_prints=True, retries=0)
def csmw_run(run_dir: str) -> str:
    """The deployment's flow: the run at `run_dir`, driven by its own loop (parallel steps
    inside), reporting the outcome. A module-level flow, because Prefect's serve executes a
    flow run in a fresh process by loading this file and looking the flow up by name."""
    from ..cli import runner_for

    return runner_for(Path(run_dir)).drive().value


def flow_for():
    """The Prefect flow object for the deployment (kept for callers that ask for it by name)."""
    return csmw_run


def serve(*, name: str = DEPLOYMENT, limit: int = 4, pause_on_shutdown: bool = False) -> None:
    """`csmw prefect serve`: the packaged process that takes runs from the server and executes
    them; one command, like the server itself (section 7.1, C6)."""
    csmw_run.serve(name=name, limit=limit, pause_on_shutdown=pause_on_shutdown, print_starting_message=True)


def run_dir_flow(run_dir: Path) -> Outcome:  # pragma: no cover - a deployment entry point
    from ..cli import runner_for

    return drive_with_prefect(runner_for(run_dir))
