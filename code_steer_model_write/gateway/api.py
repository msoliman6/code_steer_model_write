"""The control-plane operations (ARCHITECTURE.md L2), as plain functions so that the MCP
server, the CLI and the walk share one implementation. Every write goes through the same
paths a `csmw run` takes: validate through the recipe, create the run, register it, hand it
to the Runner. Reads are views of the run's own files, never a second record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..config import BackendName, Settings
from ..driver.halt import Halt
from ..events import EventLog
from ..layers.registry import RunRegistry
from ..layers.runner import LocalRunner, RunHandle, Runner
from ..spec.task import TaskSpec
from ..state.lock import atomic_write_text
from ..state.run import RunPaths, RunState


class WorkflowInfo(BaseModel):
    name: str
    version: str
    status: str
    stages: list[str]
    assumes: list[str] = Field(default_factory=list)


class RunStatus(BaseModel):
    run_id: str
    run_dir: str
    recipe: str
    status: str
    outcome: str | None = None
    steps_done: int
    steps_total: int
    current: str | None = None  # the last step started and not done
    halt: str | None = None
    verdict: str | None = None
    resumed: int = 0


class EventPage(BaseModel):
    run_id: str
    after: int
    events: list[dict[str, Any]]
    next_after: int
    more: bool


class ArtifactInfo(BaseModel):
    key: str
    versions: list[int]
    latest_path: str


class Gateway:
    """One instance per process: a runner behind the Runner seam and the registry."""

    def __init__(self, runner: Runner | None = None, registry: RunRegistry | None = None) -> None:
        self.runner: Runner = runner or self._pick_runner()
        self.registry = registry or RunRegistry()
        self.registry.add_dir(Path(Settings().runs_dir))  # this process's runs directory is always indexed

    @staticmethod
    def _pick_runner() -> Runner:
        """`CSMW_RUNNER=prefect` asks for the Prefect runner (7.3); it is used only when the
        server and the served deployment answer, otherwise the LocalRunner, and the choice is
        printed, never silent."""
        import os

        if os.environ.get("CSMW_RUNNER", "local").lower() == "prefect":
            from ..layers.prefect_runner import PrefectRunner

            pr = PrefectRunner()
            ok, why = pr.available()
            if ok:
                return pr
            print(f"runner: prefect asked for but not available ({why}); using local")
        return LocalRunner()

    # ---- workflows ---------------------------------------------------------------------------

    def list_workflows(self) -> list[WorkflowInfo]:
        from ..recipes import registry

        out = []
        for name in registry.names():
            r = registry.get(name)
            sp = r.spec
            out.append(
                WorkflowInfo(
                    name=sp.name,
                    version=sp.version,
                    status=sp.status,
                    stages=[s.title for s in sp.stages],
                    assumes=list(sp.assumes),
                )
            )
        return out

    # ---- a run's life ------------------------------------------------------------------------

    def run(
        self,
        task: dict[str, Any] | TaskSpec,
        *,
        runs_dir: str | None = None,
        run_dir: str | None = None,
        mlflow: bool = False,
    ) -> RunHandle:
        """Validate through the recipe, create the run, register it, submit it detached. The
        caller gets the run id at once and never waits (7.10)."""
        from ..backends import knobs
        from ..recipes import registry

        spec = task if isinstance(task, TaskSpec) else TaskSpec.model_validate(task)
        recipe = registry.get(spec.recipe)
        problems = recipe.validate_task(spec)
        if problems:
            raise ValueError("the task was refused: " + "; ".join(str(p) for p in problems))
        if run_dir:
            base = Path(run_dir)
            if (base / "state.json").exists():
                raise FileExistsError(f"a run already lives at {base}; resume it or choose another run_dir")
        else:
            # a second run of the same module takes the next free name: -2, -3, ... (what the
            # plugin's script and the page's start button did); the run id follows the folder
            root = Path(runs_dir or Settings().runs_dir)
            base, n = root / spec.task_id, 2
            while (base / "state.json").exists():
                base, n = root / f"{spec.task_id}-{n}", n + 1
            if base.name != spec.task_id:
                spec = spec.model_copy(update={"task_id": base.name})
        paths = RunPaths(run_dir=base)
        if knobs.enabled():
            spec = spec.model_copy(
                update={
                    "roles": {
                        r: s.model_copy(update={"backend": BackendName.FAKE}) for r, s in spec.roles.items()
                    }
                }
            )
        RunState.create(paths, spec)
        self.registry.register(paths)
        return self.runner.submit(paths, mlflow=mlflow)

    def _paths(self, run: str) -> RunPaths:
        p = Path(run)
        if (p / "state.json").exists():
            return RunPaths(run_dir=p)
        found = self.registry.find(run)
        if found is None:
            raise KeyError(f"no run named or at {run!r} in the registry")
        return found

    def status(self, run: str) -> RunStatus:
        paths = self._paths(run)
        st = RunState.load(paths)
        h = self.runner.status(paths)
        halt = Halt.read(paths)
        done = st.done_keys()
        started = [k for k, r in st.steps.items() if r.started_at is not None and r.done_at is None]
        verdict = None
        rep = paths.artifacts / "report"
        if rep.exists():
            vs = sorted(rep.glob("v*.json"))
            if vs:
                verdict = json.loads(vs[-1].read_text()).get("verdict")
        return RunStatus(
            run_id=st.run_id,
            run_dir=str(paths.run_dir),
            recipe=st.recipe,
            status=h.status,
            outcome=st.outcome.value if st.outcome else None,
            steps_done=len(done),
            steps_total=len(st.steps),
            current=started[-1] if started else None,
            halt=halt.line() if halt else None,
            verdict=verdict,
            resumed=st.resumed_count,
        )

    def cancel(self, run: str) -> RunHandle:
        return self.runner.cancel(self._paths(run))

    def pause(self, run: str) -> RunHandle:
        return self.runner.pause(self._paths(run))

    def resume(self, run: str, *, mlflow: bool = False) -> RunHandle:
        return self.runner.resume(self._paths(run), mlflow=mlflow)

    # ---- views of the record -------------------------------------------------------------------

    def get(self, run: str) -> dict[str, Any]:
        paths = self._paths(run)
        st = RunState.load(paths)
        return {
            "status": self.status(run).model_dump(),
            "task": st.task.model_dump(mode="json"),
            "steps": {k: r.model_dump(mode="json") for k, r in st.steps.items()},
        }

    def logs(self, run: str, *, after: int = 0, limit: int = 200) -> EventPage:
        """A page of the event log by `seq`, never the whole thing (the MCP output cap)."""
        paths = self._paths(run)
        st = RunState.load(paths)
        log = EventLog(paths.events, st.run_id)
        page: list[dict[str, Any]] = []
        last = after
        more = False
        for e in log.read():
            if e.seq <= after:
                continue
            if len(page) >= limit:
                more = True
                break
            page.append(e.model_dump(mode="json"))
            last = e.seq
        return EventPage(run_id=st.run_id, after=after, events=page, next_after=last, more=more)

    def artifacts(self, run: str) -> list[ArtifactInfo]:
        paths = self._paths(run)
        out = []
        if paths.artifacts.exists():
            for d in sorted(paths.artifacts.iterdir()):
                vs = sorted(int(p.stem[1:]) for p in d.glob("v*.json"))
                if vs:
                    out.append(
                        ArtifactInfo(key=d.name, versions=vs, latest_path=str(d / f"v{vs[-1]:03d}.json"))
                    )
        return out

    def list_runs(self) -> list[dict[str, Any]]:
        self.registry.scan()
        return self.registry.refresh()


def write_task_file(paths: RunPaths, task: TaskSpec) -> None:
    atomic_write_text(paths.task, task.model_dump_json(indent=2))
