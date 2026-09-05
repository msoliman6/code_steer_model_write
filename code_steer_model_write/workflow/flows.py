"""Prefect around the driver (ARCHITECTURE.md 7.3): Prefect is the Runner -- detached runs,
cancellation through its state, parallel steps as task runs, a UI -- and never the Driver.
`state.json` stays the record; Prefect's flow-run state is a view the run never reads back.

Two entry points, one loop. `csmw_run(run_dir)` is the deployment's flow: the whole run in
one flow run, with a cancellation hook that writes the halt. `drive_with_prefect` is the older
per-run form (`--prefect`). Both hand the Runner a round executor that makes every ready step
a task run, independent ones submitted together, so tests ‖ source are two task runs side by
side and Prefect's page shows each step; the Runner's own loop stays the owner of the sequence."""

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


def _task_rounds(runner: Runner):
    """A round executor for the Runner: every ready step a Prefect task run named after the
    step, independent ones submitted together (7.3: tests ‖ source side by side), so Prefect's
    page shows each step on its timeline. The Runner keeps the loop, the STOP check and the
    record; Prefect keeps the view."""
    from prefect import task

    @task(name="step", retries=0)
    def step_task(key: str) -> str | None:
        step = next(s for s in runner.driver.next() if s.key == key)
        out = runner._execute(step)
        return out.value if out is not None else None

    def run_round(ready) -> Outcome | None:
        if len(ready) == 1 or runner.parallel <= 1:
            for s in ready:
                r = step_task.with_options(task_run_name=s.key)(s.key)
                if r is not None:
                    return Outcome(r)
                if (runner.paths.run_dir / "STOP").exists():
                    break
            return None
        runner.events.append("run.progress", parallel=[s.key for s in ready])
        futures = [step_task.with_options(task_run_name=s.key).submit(s.key) for s in ready]
        results = [f.result() for f in futures]
        hit = next((r for r in results if r is not None), None)
        return Outcome(hit) if hit is not None else None

    return run_round


def drive_with_prefect(runner: Runner, *, flow_name: str | None = None) -> Outcome:
    """The older per-run form (`csmw resume --prefect`): a flow named after the run, the
    same round executor, the Runner's own loop inside."""
    from prefect import flow

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
        runner.round_executor = _task_rounds(runner)
        return runner.drive().value

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
    import os

    from ..cli import attach_mlflow, runner_for

    runner = runner_for(Path(run_dir))
    if os.environ.get("CSMW_NO_MLFLOW", "") != "1":  # the flag the served process reads (no argv here)
        attach_mlflow(runner)
    runner.round_executor = _task_rounds(runner)  # every step a task run on Prefect's page
    return runner.drive().value


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
