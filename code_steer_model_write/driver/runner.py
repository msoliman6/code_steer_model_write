"""The drive loop, in-process (rule 1): next -> execute -> done, until nothing is pending.

AUTHOR steps go through ask() and are landed by the program's code; RUN steps are
subprocesses with the exit-code contract; CODE and CHECK steps are registered functions; GATE
steps wait for a decision file (auto mode writes one, flagged). Any refusal or failure is a
halt report; a driver exception is `broke`. The loop never asks a model what to do next.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from ..ask import Accepted, CallContext, FnCheck, ask
from ..backends.base import Backend
from ..config import RoleSpec
from ..events import EventLog
from ..layers import Layers, default_layers, install
from ..layers.sandbox import Execution
from ..prompts import fill, load
from ..spec.base import CheckContext
from ..state.run import Outcome, RunnerRecord, RunPaths, RunState, RunStatus, runner_alive
from ..spec.events import now
from .driver import Driver, DriverError
from .halt import Halt, HaltReason
from .steps import Program, ProgramContext, Step, StepKind

GateWaiter = Callable[[Step, ProgramContext], bool]  # True when a decision exists (or was auto-written)


class Runner:
    def __init__(
        self,
        paths: RunPaths,
        program: Program,
        backends: dict[str, Backend],
        roles: dict[str, RoleSpec],
        gate_waiter: GateWaiter,
        *,
        poll_seconds: float = 0.5,
        gate_timeout: float | None = None,
    ) -> None:
        self.paths = paths
        self.program = program
        self.backends = backends
        self.roles = roles
        self.gate_waiter = gate_waiter
        self.poll = poll_seconds
        self.gate_timeout = gate_timeout
        state = RunState.load(paths)
        self.events = EventLog(paths.events, state.run_id)
        self.driver = Driver(paths, program, self.events)
        self.layers: Layers = install(default_layers(paths, self.events))

    # ---- lifecycle -----------------------------------------------------------------------

    def _set(self, status: RunStatus, outcome: Outcome | None = None, **extra: Any) -> None:
        st = self.driver.state
        st.status = status
        if outcome is not None:
            st.outcome = outcome
        if status is RunStatus.COMPLETED:
            st.completed_at = now()
        st.save(self.paths)
        self.events.append(
            "run.status", status=status.value, outcome=outcome.value if outcome else None, **extra
        )

    def begin(self) -> Outcome | None:
        """Clear a halt (resume), mark RUNNING, take the runner record. Returns an outcome only
        if the run cannot start (another live runner holds it)."""
        st = self.driver.state
        if runner_alive(self.paths):
            other = RunnerRecord.read(self.paths)
            self.events.append(
                "run.status",
                status="REFUSED",
                reason=f"another runner (pid {other.pid if other else '?'}) holds this run",
            )
            return Outcome.BROKE
        self._record = RunnerRecord(pid=os.getpid(), host=socket.gethostname())
        self._record.write(self.paths)
        self._beat = threading.Thread(target=self._heartbeat, daemon=True)
        self._beat_stop = threading.Event()
        self._beat.start()
        h = Halt.read(self.paths)
        if h is not None:
            Halt.clear(self.paths)
            st.resumed_count += 1
            st.last_halt = h.line()
            st.save(self.paths)
            self.events.append("run.status", status="RESUMED", from_step=h.step)
        self._set(RunStatus.RUNNING)
        return None

    def _heartbeat(self) -> None:
        while not self._beat_stop.wait(5):
            try:
                self._record.alive_at = now()
                self._record.write(self.paths)
            except Exception:  # noqa: BLE001 -- a heartbeat that cannot write must not kill the run
                pass

    def _close_record(self) -> None:
        rec = getattr(self, "_record", None)
        if rec is None:
            return
        self._beat_stop.set()
        rec.ended_at = now()
        rec.write(self.paths)

    def finish(self) -> Outcome:
        """Nothing is ready: complete, or report a blocked program."""
        if self.driver.is_complete():
            self._set(RunStatus.COMPLETED, Outcome.COMPLETED)
            return Outcome.COMPLETED
        pend = [s.key for s in self.driver.all_pending()]
        return self._halt(
            Halt(
                step=pend[0],
                reason=HaltReason.BROKE,
                resumable=False,
                message=f"pending steps with no ready step: {pend} (a dependency cycle or a missing after)",
            )
        )

    def drive(self) -> Outcome:
        try:
            out = self.begin()
            if out is not None:
                return out
            while True:
                if (self.paths.run_dir / "STOP").exists():
                    (self.paths.run_dir / "STOP").unlink()
                    pend = [s.key for s in self.driver.all_pending()]
                    return self._halt(
                        Halt(
                            step=pend[0] if pend else "end",
                            reason=HaltReason.CANCELLED,
                            message="stopped from the page",
                            resumable=True,
                        )
                    )
                ready = self.driver.next()
                if not ready:
                    return self.finish()
                for step in ready:
                    outcome = self._execute(step)
                    if outcome is not None:
                        return outcome
                    if (self.paths.run_dir / "STOP").exists():
                        break
        except Exception as e:  # noqa: BLE001 -- the driver itself broke; report, never crash silently
            tb = traceback.format_exc(limit=8)
            return self._halt(
                Halt(
                    step="driver",
                    reason=HaltReason.BROKE,
                    message=f"{type(e).__name__}: {e}",
                    facts=[{"traceback": tb}],
                    resumable=False,
                )
            )
        finally:
            self._close_record()

    def _halt(self, h: Halt) -> Outcome:
        h.write(self.paths)
        self.events.append(
            "halt", step=h.step, reason=h.reason.value, message=h.message, resumable=h.resumable
        )
        outcome = Outcome.HALTED_HONESTLY if h.resumable else Outcome.BROKE
        self._set(RunStatus.PAUSED if h.resumable else RunStatus.FAILED, outcome, message=h.message)
        return outcome

    # ---- one step ------------------------------------------------------------------------

    def _ctx(self, step: Step) -> ProgramContext:
        return ProgramContext(
            state=self.driver.state, paths=self.paths, store=self.driver.store, step=step, events=self.events
        )

    def _principal(self, step: Step):
        return self.layers.identity.side(step.role) if step.role else self.layers.identity.user()

    def _spent(self, role: str) -> int:
        """Tokens this role has spent so far, from the record (rule 4: the log is the owner)."""
        total = 0
        for e in self.events.read():
            if e.kind == "call.usage" and e.role == role:
                total += int(e.data.get("input_tokens", 0)) + int(e.data.get("output_tokens", 0))
        return total

    def _execute(self, step: Step) -> Outcome | None:
        # L2 budgets (P1): the ceiling is a fact the task owns; the check happens before the
        # step is issued (section 4, L2); a run over its ceiling halts honestly, resumable
        if step.kind is StepKind.AUTHOR and step.role:
            ceiling = self.roles[step.role].budget_tokens
            if ceiling is not None:
                spent = self._spent(step.role)
                if spent >= ceiling:
                    return self._halt(
                        Halt(
                            step=step.key,
                            reason=HaltReason.BUDGET,
                            message=f"{step.role} spent {spent} tokens of a {ceiling} ceiling",
                            resumable=True,
                        )
                    )
        # L9 at issue (section 2: a step is issued -> may this side author or judge this artifact?)
        who = self._principal(step)
        action = "author" if step.kind is StepKind.AUTHOR else "issue"
        d = self.layers.policy.decide(who, action, step.land or step.key, {"kind": step.kind.value})
        if not d:
            return self._halt(
                Halt(step=step.key, reason=HaltReason.BROKE, message=f"denied: {d.reason}", resumable=False)
            )
        self.driver.start(step.key)
        ctx = self._ctx(step)
        try:
            if step.kind is StepKind.AUTHOR:
                return self._author(step, ctx)
            if step.kind is StepKind.RUN:
                return self._run(step, ctx)
            if step.kind is StepKind.CODE:
                self.program.code_steps[step.fn](ctx)  # type: ignore[index]
                self.driver.done(step.key)
                return None
            if step.kind is StepKind.CHECK:
                problems = self.program.checks[step.fn](ctx)  # type: ignore[index]
                self.events.append("check.result", step=step.key, problems=problems)
                if problems and step.on_problems == "halt":
                    return self._halt(
                        Halt(step=step.key, reason=HaltReason.CHECK_FAILED, message="; ".join(problems))
                    )
                self.driver.done(step.key)
                return None
            if step.kind is StepKind.GATE:
                return self._gate(step, ctx)
            raise DriverError(f"unknown step kind {step.kind}")
        except DriverError as e:
            return self._halt(Halt(step=step.key, reason=HaltReason.MISSING_DELIVERABLE, message=str(e)))

    def _author(self, step: Step, ctx: ProgramContext) -> Outcome | None:
        assert step.prompt and step.schema_name and step.role
        schema = self.program.schemas[step.schema_name]
        t = load(step.prompt, self.program.prompts_root)
        prompt = fill(
            t, step.sets, schema=schema, rendered_keys=step.rendered_keys, needs_tools=step.needs_tools
        )

        def _check(n: str):
            def run(a, c):
                ctx.answer = a  # the artifact under check (rule 7)
                return [self._problem(p) for p in self.program.checks[n](ctx)]

            return FnCheck(n, run)

        checks = [_check(n) for n in step.checks]
        known = set(ctx.extra.get("known_ids", [])) | _known_ids(ctx)
        role_spec = self.roles[step.role]
        if step.model or step.effort:
            role_spec = role_spec.model_copy(
                update={k: v for k, v in (("model", step.model), ("effort", step.effort)) if v}
            )
        cctx = CallContext(
            backend=self.backends[role_spec.backend.value],
            role_spec=role_spec,
            events=self.events,
            step=step.key,
            streams_dir=self.paths.streams,
            scope_root=self.paths.resolve(step.cwd) if step.needs_tools and step.cwd else None,
            check_ctx=CheckContext(known_ids=known, step=step.key, extra=dict(step.check_extra)),
            fixture=step.fixture,
            rails=self.layers.rails,
        )
        r = ask(prompt, schema, role=step.role, ctx=cctx, checks=checks)
        if isinstance(r, Accepted):
            produced = self.program.land(step, r.value, ctx)
            for d in produced:
                self.events.append("artifact.written", step=step.key, path=d)
            self.driver.done(step.key, produced)
            return None
        reason = HaltReason.BACKEND if r.reason == "backend" else HaltReason.REFUSED
        last = r.problems_by_attempt[-1] if r.problems_by_attempt else []
        return self._halt(
            Halt(
                step=step.key,
                reason=reason,
                message=f"{r.message}" + (f"; last problems: {last}" if last else ""),
                facts=[f.model_dump(mode="json") for f in r.facts],
            )
        )

    @staticmethod
    def _problem(text: str):
        from ..spec.base import Problem

        code, _, msg = text.partition(":")
        return Problem(code=code.strip() or "check", message=msg.strip() or text)

    def _run(self, step: Step, ctx: ProgramContext) -> Outcome | None:
        assert step.command
        cwd = self.paths.resolve(step.cwd) if step.cwd else self.paths.run_dir
        self.paths.streams.mkdir(parents=True, exist_ok=True)
        out_path = self.paths.streams / f"{step.key}.out.txt"
        # L9 at execute, then L5 (section 2: nothing enters L5 except through L6; a RUN step is
        # the one legacy path that hands L5 a command directly -- recorded as such)
        d = self.layers.policy.decide(
            self._principal(step), "execute", step.key, {"root": self.paths.run_dir, "cwd": cwd}
        )
        if not d:
            return self._halt(
                Halt(step=step.key, reason=HaltReason.BROKE, message=f"denied: {d.reason}", resumable=False)
            )
        proc = self.layers.sandbox.run(
            Execution(command=step.command, root=self.paths.run_dir, cwd=cwd, step=step.key, tool="run-step")
        )
        out_path.write_text(
            proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else ""), encoding="utf-8"
        )
        self.events.append("call.final", step=step.key, exit_code=proc.exit_code, seconds=proc.seconds)
        if proc.exit_code != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-6:]
            return self._halt(
                Halt(
                    step=step.key,
                    reason=HaltReason.RUN_FAILED,
                    command=step.command,
                    message=f"exit {proc.exit_code}",
                    facts=[{"line": ln} for ln in tail],
                )
            )
        self.driver.done(step.key)
        return None

    def _gate(self, step: Step, ctx: ProgramContext) -> Outcome | None:
        t0 = time.time()
        while not self.gate_waiter(step, ctx):
            if self.gate_timeout is not None and time.time() - t0 > self.gate_timeout:
                return self._halt(
                    Halt(step=step.key, reason=HaltReason.CANCELLED, message="gate wait timed out")
                )
            time.sleep(self.poll)
        self.driver.done(step.key)
        return None


def _known_ids(ctx: ProgramContext) -> set[str]:
    """Every id in every artifact on disk (rule 5): a cite must resolve to one of these."""
    from ..ids import find_ids

    ids: set[str] = set()
    root: Path = ctx.paths.artifacts
    if root.exists():
        for p in root.rglob("*.json"):
            ids |= set(find_ids(p.read_text(encoding="utf-8")))
    return ids
