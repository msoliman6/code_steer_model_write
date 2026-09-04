"""L3's Runner seam (ARCHITECTURE.md section 6): submit a run detached, cancel, pause, resume,
report liveness. It never decides sequence: the Driver does, from disk. First implementation
`LocalRunner`: the mechanics the plugin's `start.sh` and the page's start button used to hold
-- a detached `csmw resume` process, liveness from `runner.json`, cancel and pause by the STOP
file the drive loop honours at the next step boundary. Prefect replaces it in phase 5 behind
the same seam."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from ..state.lock import atomic_write_text
from ..state.run import RunPaths, RunState, RunnerRecord, runner_alive


class RunHandle(BaseModel):
    run_id: str
    run_dir: str
    status: str
    pid: int | None = None


class Runner(Protocol):
    name: str

    def submit(self, paths: RunPaths, *, mlflow: bool = False) -> RunHandle: ...
    def cancel(self, paths: RunPaths, *, reason: str = "cancelled") -> RunHandle: ...
    def pause(self, paths: RunPaths) -> RunHandle: ...
    def resume(self, paths: RunPaths, *, mlflow: bool = False) -> RunHandle: ...
    def status(self, paths: RunPaths) -> RunHandle: ...


def _handle(paths: RunPaths, pid: int | None = None) -> RunHandle:
    st = RunState.load(paths)
    live = runner_alive(paths)
    status = st.status.value
    if status == "RUNNING" and not live:
        status = "STALE"  # a RUNNING state whose runner is gone (ledger: an exit code that lies)
    rec = RunnerRecord.read(paths)
    return RunHandle(
        run_id=st.run_id,
        run_dir=str(paths.run_dir),
        status=status,
        pid=pid or (rec.pid if rec and live else None),
    )


class LocalRunner:
    name = "local"

    def __init__(self, python: str | None = None, cwd: Path | None = None) -> None:
        self.python = python or sys.executable
        self.cwd = cwd or Path.cwd()

    def _spawn(self, paths: RunPaths, *, mlflow: bool) -> RunHandle:
        cmd = [self.python, "-m", "code_steer_model_write.cli", "resume", str(paths.run_dir)]
        if not mlflow:
            cmd.append("--no-mlflow")
        log = (paths.run_dir / "runner.log").open("a")
        env = dict(os.environ)
        proc = subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=str(self.cwd), env=env
        )
        return RunHandle(
            run_id=RunState.load(paths).run_id, run_dir=str(paths.run_dir), status="RUNNING", pid=proc.pid
        )

    def submit(self, paths: RunPaths, *, mlflow: bool = False) -> RunHandle:
        if runner_alive(paths):
            return _handle(paths)
        return self._spawn(paths, mlflow=mlflow)

    def cancel(self, paths: RunPaths, *, reason: str = "cancelled from the gateway") -> RunHandle:
        atomic_write_text(paths.run_dir / "STOP", reason)  # honoured at the next step boundary
        return _handle(paths)

    def pause(self, paths: RunPaths) -> RunHandle:
        return self.cancel(paths, reason="paused from the gateway")  # a halt is a report; resume continues

    def resume(self, paths: RunPaths, *, mlflow: bool = False) -> RunHandle:
        return self.submit(paths, mlflow=mlflow)

    def status(self, paths: RunPaths) -> RunHandle:
        return _handle(paths)


Status = Literal["RUNNING", "PAUSED", "COMPLETED", "FAILED", "CANCELLED", "STALE"]
