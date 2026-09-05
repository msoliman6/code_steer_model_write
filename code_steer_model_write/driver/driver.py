"""next / done / undo -- code decides what happens next and whether it counts (rule 1).

`next()` asks the program for its steps (derived from disk), drops the ones whose record and
deliverables both say done, and returns the ready ones. `done()` refuses a step whose
deliverables are missing. `undo()` forgets a half-done step by moving its deliverables aside.
"""

from __future__ import annotations

import shutil
from datetime import datetime

from ..artifacts.store import Store
from ..events import EventLog
from ..spec.events import now
from ..state.run import RunPaths, RunState, StepRecord
from .steps import Program, Step


class DriverError(RuntimeError):
    pass


class Driver:
    def __init__(self, paths: RunPaths, program: Program, events: EventLog | None = None) -> None:
        self.paths = paths
        self.program = program
        self.store = Store(paths.run_dir)
        self.events = events or EventLog(paths.events, RunState.load(paths).run_id)

    @property
    def state(self) -> RunState:
        return RunState.load(self.paths)

    def _delivered(self, step: Step) -> list[str]:
        return [d for d in step.deliverables if not self.paths.resolve(d).exists()]

    def all_steps(self) -> list[Step]:
        return self.program.steps(self.state, self.paths, self.store)

    def next(self) -> list[Step]:
        """The ready steps: pending, every `after` done. Empty means the program has nothing
        more to issue (done, or blocked on a gate the program still lists)."""
        st = self.state
        steps = self.all_steps()
        done: set[str] = set()
        reopened: list[str] = []
        for s in steps:
            rec = st.steps.get(s.key)
            if rec and rec.done_at is not None:
                missing = self._delivered(s)
                if missing:
                    reopened.append(s.key)  # reopened under the lock below, never on this copy
                else:
                    done.add(s.key)
        pending = [s for s in steps if s.key not in done]
        ready = [s for s in pending if all(a in done for a in s.after)]

        def apply(cur: RunState) -> list[str]:
            issued: list[str] = []
            for k in reopened:
                rec = cur.steps.get(k)
                if rec is not None:
                    rec.done_at = None
                    rec.deliverables = []
            for s in ready:
                if s.key not in cur.steps:
                    cur.steps[s.key] = StepRecord(key=s.key, kind=s.kind.value)
                    issued.append(s.key)
            return issued

        issued = RunState.update(self.paths, apply) if (reopened or ready) else []
        for k in reopened:
            self.events.append("step.issued", step=k, reopened=True, reason="deliverable missing")
        for s in ready:
            if s.key in issued:
                self.events.append("step.issued", step=s.key, step_kind=s.kind.value, phase=s.phase)
        return ready

    def start(self, key: str) -> None:
        def apply(st: RunState) -> int:
            rec = st.steps.get(key)
            if rec is None:
                raise DriverError(f"step {key!r} was never issued")
            rec.started_at = now()
            rec.attempts += 1
            return rec.attempts

        attempts = RunState.update(self.paths, apply)
        self.events.append("step.started", step=key, attempt=attempts)

    def done(self, key: str, deliverables: list[str] | None = None) -> None:
        if key not in self.state.steps:
            raise DriverError(f"step {key!r} was never issued")
        step = next((s for s in self.all_steps() if s.key == key), None)
        required = list(step.deliverables) if step else []
        required += [d for d in (deliverables or []) if d not in required]
        missing = [d for d in required if not self.paths.resolve(d).exists()]
        if missing:
            raise DriverError(f"step {key!r} claims done but deliverables are missing: {missing}")

        def apply(cur: RunState) -> None:
            r = cur.steps.get(key)
            if r is None:
                raise DriverError(f"step {key!r} was never issued")
            r.done_at = now()
            r.deliverables = required

        RunState.update(self.paths, apply)
        self.events.append("step.done", step=key, deliverables=required)

    def undo(self, key: str) -> None:
        rec = RunState.update(self.paths, lambda cur: cur.steps.pop(key, None))
        if rec is None:
            raise DriverError(f"nothing to undo: step {key!r} has no record")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        moved: list[str] = []
        for d in rec.deliverables:
            src = self.paths.resolve(d)
            if src.exists():
                dst = self.paths.undone / stamp / d
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved.append(d)
        self.events.append("step.undone", step=key, moved=moved)

    def is_complete(self) -> bool:
        return not self.all_pending()

    def all_pending(self) -> list[Step]:
        done = self.state.done_keys()
        return [s for s in self.all_steps() if s.key not in done]
