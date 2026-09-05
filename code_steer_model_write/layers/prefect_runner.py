"""L3's second Runner (ARCHITECTURE.md 7.3): Prefect 3. A run is submitted to the served
deployment and executes under Prefect's process; cancellation goes through Prefect's state
(the flow's cancel hook writes the halt), pause is the same halt, resume is a new submission
of the same run directory (the Driver continues from disk). Liveness is the run's own record
first, Prefect's flow-run state second -- a view, never read back into the run.

Needs `prefect server start` and `csmw prefect serve` running: two packaged processes, one
command each. Without them the Gateway falls back to the LocalRunner and says so."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ..state.lock import atomic_write_text
from ..state.run import RunPaths, RunState, runner_alive
from ..workflow.names import DEPLOYMENT, FLOW_NAME
from .runner import RunHandle, _handle


def _run(coro: Any) -> Any:
    """Run a coroutine to completion from sync code, whether or not an event loop is already
    running in this thread (a page's handler, an MCP tool): under a running loop it goes to a
    worker thread with a loop of its own. `asyncio.run` alone raised there, the probe reported
    "unavailable", and the Gateway fell back to the LocalRunner with only a print to say so."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="prefect") as pool:
        return pool.submit(asyncio.run, coro).result()


class PrefectRunner:
    name = "prefect"

    def __init__(self, deployment: str = f"{FLOW_NAME}/{DEPLOYMENT}") -> None:
        self.deployment = deployment

    # ---- the flow-run id lives beside the run, never in the record ----------------------------

    @staticmethod
    def _id_path(paths: RunPaths) -> Path:
        return paths.run_dir / "prefect.json"

    def _flow_run_id(self, paths: RunPaths) -> str | None:
        p = self._id_path(paths)
        return json.loads(p.read_text()).get("flow_run_id") if p.exists() else None

    def available(self) -> tuple[bool, str]:
        """Is the server reachable and the deployment served? Said in words, never assumed."""
        try:
            from prefect.client.orchestration import get_client

            async def probe() -> tuple[bool, str]:
                async with get_client() as c:
                    await c.api_healthcheck()
                    await c.read_deployment_by_name(self.deployment)  # raises when not served
                    return True, f"deployment {self.deployment} on {c.api_url}"

            return _run(probe())
        except Exception as e:  # noqa: BLE001 -- the reason travels to the caller
            return False, f"{type(e).__name__}: {str(e)[:160]}"

    def submit(self, paths: RunPaths, *, mlflow: bool = False) -> RunHandle:
        if runner_alive(paths):
            return _handle(paths)
        from prefect.deployments import run_deployment

        fr: Any = run_deployment(
            self.deployment, parameters={"run_dir": str(paths.run_dir)}, timeout=0, as_subflow=False
        )
        if asyncio.iscoroutine(fr):  # sync-compatible in Prefect 3; typed as async
            fr = _run(fr)
        atomic_write_text(
            self._id_path(paths), json.dumps({"flow_run_id": str(fr.id), "deployment": self.deployment})
        )
        st = RunState.load(paths)
        return RunHandle(
            run_id=st.run_id, run_dir=str(paths.run_dir), status="RUNNING", pid=None, runner=self.name
        )

    def cancel(self, paths: RunPaths, *, reason: str = "cancelled through Prefect") -> RunHandle:
        fid = self._flow_run_id(paths)
        atomic_write_text(paths.run_dir / "STOP", reason)  # the loop's own boundary, in case Prefect is slow
        if fid:
            from prefect.client.orchestration import get_client
            from prefect.states import Cancelling

            async def do() -> None:
                async with get_client() as c:
                    await c.set_flow_run_state(fid, Cancelling(), force=True)

            try:
                _run(do())
            except Exception:  # noqa: BLE001 -- the STOP file still stops the run at its next boundary
                pass
        return _handle(paths)

    def pause(self, paths: RunPaths) -> RunHandle:
        return self.cancel(paths, reason="paused through Prefect")

    def resume(self, paths: RunPaths, *, mlflow: bool = False) -> RunHandle:
        return self.submit(paths, mlflow=mlflow)

    def status(self, paths: RunPaths) -> RunHandle:
        return _handle(paths)
