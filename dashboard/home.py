"""The home page's data (docs/PLAN.md §7d, pieces 1 and 4): every run the registry knows, one
row each, from the run's own files -- `state.json` (status, steps, clock), `events.jsonl`
(tokens), the report artifact (verdict), `evals.json` (the eval columns). The registry is the
one owner of the list; this module reads and never writes. Pure functions over the rows for
the filters, the sort, the counters and the trends, so the self-check proves the page by code.

A row is rebuilt only when its run's files moved (the cache keys on the mtimes), so the poll
over twenty runs costs twenty stats, not twenty parses."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from code_steer_model_write import config
from code_steer_model_write.events import EventLog
from code_steer_model_write.state.run import RunPaths, RunState, runner_alive

from . import theme as T

EVAL_COLUMNS = ("pass_rate", "null_fail_rate", "carried_findings", "rounds_to_converge", "refused_answers")
STATUSES = ("all", "running", "completed", "halted", "failed", "stale", "queued")


class HomeRow(BaseModel):
    id: str
    recipe: str
    status: str  # RUNNING | COMPLETED | PAUSED | FAILED | STALE | QUEUED
    bucket: str  # running | completed | halted | failed | stale | queued (the filter's words)
    verdict: str = ""
    steps_done: int = 0
    steps_total: int = 0
    steps: str = ""
    elapsed: str = ""
    seconds: float = 0.0
    tokens: int = 0
    tokens_label: str = ""
    cost: str = ""
    cost_note: str = ""
    evals: dict[str, str] = {}  # metric -> value as shown; "" when the run has no evals.json
    eval_values: dict[str, float] = {}  # metric -> number, for the trends
    started: str = ""
    started_at: datetime | None = None
    dir: str
    dot: str = "queued"
    ring: str = ""
    resumed: int = 0
    halt: str = ""


_cache: dict[str, tuple[tuple[float, ...], HomeRow]] = {}


def run_dot(d: Path, st: dict[str, Any]) -> tuple[str, str]:
    """A run's dot from its files, cheap, no events read: green running, amber waiting for you,
    red halted or broke, grey done (ringed green when clean, amber when items carried). The one
    owner for the tab strip and the home."""
    status = st.get("status", "")
    if status in ("PAUSED", "FAILED", "CANCELLED") or (d / "halt.json").exists():
        return "halted", ""
    if status == "RUNNING" and not runner_alive(RunPaths(run_dir=d)):
        return "halted", ""  # stale: the record says running, the runner is gone
    if status == "COMPLETED":
        return "done", ("warn" if st.get("carried") else "ok")
    gates = d / "gates"
    if gates.exists() and any(
        not (gates / (g.name[: -len(".ask.json")] + ".decision.json")).exists()
        for g in gates.glob("*.ask.json")
    ):
        return "waiting", ""
    return ("running", "") if status == "RUNNING" else ("queued", "")


def _halt_text(paths: RunPaths) -> str:
    """The halt as the run reports it (`halt.json`, the record), the step and the reason."""
    from code_steer_model_write.driver.halt import Halt

    h = Halt.read(paths)
    return f"{h.step}: {h.message}" if h is not None else ""


def _bucket(status: str) -> str:
    return {
        "RUNNING": "running",
        "COMPLETED": "completed",
        "PAUSED": "halted",
        "FAILED": "failed",
        "STALE": "stale",
        "QUEUED": "queued",
    }.get(status, status.lower())


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}h{(s % 3600) // 60:02d}"


def _mtimes(d: Path) -> tuple[float, ...]:
    out = []
    for name in ("state.json", "events.jsonl", "evals.json", "halt.json", "runner.json"):
        p = d / name
        out.append(p.stat().st_mtime if p.exists() else 0.0)
    rep = d / "artifacts" / "report"
    out.append(max((p.stat().st_mtime for p in rep.glob("v*.json")), default=0.0) if rep.exists() else 0.0)
    return tuple(out)


def row_for(run_dir: Path | str, *, now: datetime | None = None) -> HomeRow:
    """One run's row from its files. The dot and ring are the tab strip's (`model.run_dot`), so
    the strip and the home never disagree about a run's colour."""
    d = Path(run_dir)
    key = _mtimes(d)
    hit = _cache.get(str(d))
    if hit and hit[0] == key and hit[1].bucket != "running":
        return hit[1]
    paths = RunPaths(run_dir=d)
    st = RunState.load(paths)
    now = now or datetime.now(timezone.utc)
    status = st.status.value
    if status == "RUNNING" and not runner_alive(paths):
        status = "STALE"
    evs = EventLog(paths.events, st.run_id).all() if paths.events.exists() else []
    started_at = st.created_at
    end = st.completed_at or (evs[-1].ts if evs and status not in ("RUNNING",) else now)
    seconds = max(0.0, (end - started_at).total_seconds())
    io: dict[str, list[int]] = {}
    models = {r: s.model for r, s in st.task.roles.items()}
    for e in evs:
        if e.kind == "call.usage" and e.role:
            v = io.setdefault(e.role, [0, 0, 0])
            v[0] += int(e.data.get("input_tokens", 0) or 0)
            v[1] += int(e.data.get("output_tokens", 0) or 0)
            v[2] += int(e.data.get("cache_read_tokens", 0) or 0)
    tokens = sum(v[0] + v[1] for v in io.values())
    costs = [config.cost_usd(models.get(r, ""), *v) for r, v in io.items()]
    known = [c for c in costs if c is not None]
    cost = config.usd(sum(known) if costs and len(known) == len(costs) else None) if io else ""
    backends = {str(s.backend.value) for s in st.task.roles.values()}
    verdict = ""
    rep = paths.artifacts / "report"
    if rep.exists():
        vs = sorted(rep.glob("v*.json"))
        if vs:
            try:
                verdict = str(json.loads(vs[-1].read_text()).get("verdict") or "")
            except ValueError:
                verdict = ""
    evals: dict[str, str] = {}
    eval_values: dict[str, float] = {}
    ep = d / "evals.json"
    if ep.exists():
        try:
            for r in json.loads(ep.read_text()).get("results", []):
                m = str(r.get("metric"))
                val = r.get("value")
                if isinstance(val, (int, float)):
                    eval_values[m] = float(val)
                    evals[m] = f"{val:.2f}".rstrip("0").rstrip(".") if isinstance(val, float) else str(val)
        except ValueError:
            pass
    dot, ring = run_dot(d, {"status": st.status.value, "carried": st.carried})
    done = sum(1 for r in st.steps.values() if r.done_at is not None)
    row = HomeRow(
        id=st.run_id,
        recipe=st.recipe,
        status=status,
        bucket=_bucket(status),
        verdict=verdict,
        steps_done=done,
        steps_total=len(st.steps),
        steps=f"{done}/{len(st.steps)}",
        elapsed=_fmt_dur(seconds),
        seconds=round(seconds, 1),
        tokens=tokens,
        tokens_label=T.k(tokens) if tokens else "",
        cost=cost,
        cost_note="at API rates" if backends & {"claude_cli", "codex_cli"} else "",
        evals=evals,
        eval_values=eval_values,
        started=started_at.astimezone().strftime("%m-%d %H:%M"),
        started_at=started_at,
        dir=str(d),
        dot=dot,
        ring=ring,
        resumed=st.resumed_count,
        halt=_halt_text(paths),
    )
    _cache[str(d)] = (key, row)
    return row


def rows(registry, *, now: datetime | None = None) -> list[HomeRow]:
    """Every run the registry lists (hidden ones excluded), newest first."""
    registry.scan()
    out: list[HomeRow] = []
    for r in registry.refresh():
        d = Path(r["run_dir"])
        if not (d / "state.json").exists():
            continue
        try:
            out.append(row_for(d, now=now))
        except Exception:  # noqa: BLE001 -- a half-written run dir is skipped, never fatal to the home
            continue
    out.sort(key=lambda r: r.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


# ---- pure functions over the rows ------------------------------------------------------------


def filtered(
    rs: list[HomeRow], *, status: str = "all", recipe: str = "all", query: str = ""
) -> list[HomeRow]:
    q = query.strip().lower()
    return [
        r
        for r in rs
        if (status == "all" or r.bucket == status)
        and (recipe == "all" or r.recipe == recipe)
        and (not q or q in r.id.lower() or q in r.verdict.lower())
    ]


SORT_KEYS: dict[str, Any] = {
    "started": lambda r: r.started_at or datetime.min.replace(tzinfo=timezone.utc),
    "id": lambda r: r.id,
    "recipe": lambda r: r.recipe,
    "status": lambda r: r.bucket,
    "steps": lambda r: (r.steps_done, r.steps_total),
    "elapsed": lambda r: r.seconds,
    "tokens": lambda r: r.tokens,
    "cost": lambda r: r.cost,
}


def _eval_key(metric: str):
    return lambda r: r.eval_values.get(metric, float("-inf"))


for _m in EVAL_COLUMNS:
    SORT_KEYS[_m] = _eval_key(_m)


def sorted_rows(rs: list[HomeRow], key: str = "started", desc: bool = True) -> list[HomeRow]:
    f = SORT_KEYS.get(key, SORT_KEYS["started"])
    return sorted(rs, key=f, reverse=desc)


def counters(rs: list[HomeRow]) -> dict[str, int]:
    """The four counters above the table, and the rest for the filter chips."""
    c = {k: 0 for k in STATUSES if k != "all"}
    for r in rs:
        c[r.bucket] = c.get(r.bucket, 0) + 1
    c["all"] = len(rs)
    return c


def recipes(rs: list[HomeRow]) -> list[str]:
    return sorted({r.recipe for r in rs})


def trends(rs: list[HomeRow], recipe: str, n: int = 20) -> list[dict[str, Any]]:
    """The eval values of the last `n` finished runs of one recipe, oldest first, one point per
    run, for the small charts above the table. A run without evals is not a point."""
    pts = [r for r in rs if r.recipe == recipe and r.eval_values]
    pts.sort(key=lambda r: r.started_at or datetime.min.replace(tzinfo=timezone.utc))
    return [{"run": r.id, **{m: r.eval_values.get(m) for m in EVAL_COLUMNS}} for r in pts[-n:]]
