"""The step timeline (docs/PLAN.md §7d, piece 2): one row per step from the run's own events,
a bar from `step.started` to `step.done` on the run's clock, the model call a darker segment
inside it, tokens at the row's end. Overlapping rows show the parallel build. A pure function,
`events -> rows`, so the self-check proves the page's rows against the record without a browser."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from code_steer_model_write.spec.events import Event


class TimelineRow(BaseModel):
    step: str
    kind: str = ""  # the step kind the record carries: author | judge | code | check | gate | tool
    role: str = ""
    lane: str = "code"  # the swimlane's letter for the role (a, b, you) or code
    start: float  # seconds from the run's first event
    end: float
    call_start: float | None = None  # the model call inside the step, when there was one
    call_end: float | None = None
    tokens: int = 0
    done: bool = False


def rows(evs: list[Event], *, now: datetime | None = None) -> list[TimelineRow]:
    """Rows in the order the steps started. A step still running ends at `now`; a call still
    open ends where its step ends."""
    if not evs:
        return []
    t0 = evs[0].ts
    now = now or evs[-1].ts

    def at(ts: datetime) -> float:
        return round((ts - t0).total_seconds(), 3)

    by_step: dict[str, dict] = {}
    for e in evs:
        if not e.step:
            continue
        r = by_step.setdefault(
            e.step, {"kind": "", "role": "", "start": None, "end": None, "c0": None, "c1": None, "tokens": 0}
        )
        if e.kind == "step.issued":
            r["kind"] = str(e.data.get("step_kind", r["kind"]))
        elif e.kind == "step.started":
            r["start"] = at(e.ts)
            r["role"] = e.role or r["role"]
        elif e.kind == "step.done":
            r["end"] = at(e.ts)
        elif e.kind == "call.started":
            if r["c0"] is None:
                r["c0"] = at(e.ts)
            r["role"] = r["role"] or (e.role or "")
        elif e.kind in ("call.final", "call.error"):
            r["c1"] = at(e.ts)
        elif e.kind == "call.usage":
            r["tokens"] += int(e.data.get("input_tokens", 0) or 0) + int(e.data.get("output_tokens", 0) or 0)
            r["c1"] = at(e.ts)
    out: list[TimelineRow] = []
    for step, r in by_step.items():
        if r["start"] is None:
            continue  # issued, never started: not on the clock
        end = r["end"] if r["end"] is not None else at(now)
        c0 = r["c0"]
        c1 = r["c1"] if r["c1"] is not None else (end if c0 is not None else None)
        out.append(
            TimelineRow(
                step=step,
                kind=r["kind"],
                role=r["role"],
                start=r["start"],
                end=max(end, r["start"]),
                call_start=c0,
                call_end=c1,
                tokens=r["tokens"],
                done=r["end"] is not None,
            )
        )
    out.sort(key=lambda r: (r.start, r.step))
    return out


def overlaps(rs: list[TimelineRow]) -> list[tuple[str, str, float]]:
    """Pairs of steps whose bars overlap in time, with the overlap in seconds: the parallel build
    shows here as (tests, source, 50.1)."""
    out = []
    for i, a in enumerate(rs):
        for b in rs[i + 1 :]:
            lo, hi = max(a.start, b.start), min(a.end, b.end)
            if hi > lo:
                out.append((a.step, b.step, round(hi - lo, 3)))
    return out
