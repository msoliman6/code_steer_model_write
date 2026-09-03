"""Prefect around the driver (rule 1): a flow loops `next()`, each step runs as a task named by
its key, a cancellation writes CANCELLED. Prefect is a scheduler, a cancel channel and a view;
state.json stays the owner. `Runner.drive()` without Prefect runs the same loop in-process
(the walk uses it) -- one loop, two harnesses."""

from __future__ import annotations

from pathlib import Path

from ..driver.halt import Halt, HaltReason
from ..driver.runner import Runner
from ..state.run import Outcome


def drive_with_prefect(runner: Runner, *, flow_name: str | None = None) -> Outcome:
    from prefect import flow, task

    @task(name="step", retries=0)
    def step_task(key: str) -> str | None:
        step = next(s for s in runner.driver.next() if s.key == key)
        out = runner._execute(step)
        return out.value if out is not None else None

    def on_cancel(flow_, flow_run, state) -> None:
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
            for s in ready:
                r = step_task.with_options(task_run_name=s.key)(s.key)
                if r is not None:
                    return r

    return Outcome(drive_flow())


def run_dir_flow(run_dir: Path) -> Outcome:  # pragma: no cover - a deployment entry point
    from ..cli import runner_for

    return drive_with_prefect(runner_for(run_dir))
