"""The page's view model, built from the run's files by code (docs/PLAN.md §7; rule 4, 10).

One function, `build_view(run_dir)`, reads state.json (status), events.jsonl (everything live),
the gate and halt files, and returns every signal the page shows: where (the rail), healthy
(process and product), time (elapsed, tokens per side), the NOW line, the wrong-ness chips, the
selected stage's panel, the evidence. The self-check asserts on this model without a browser;
the Reflex components only render it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from code_steer_model_write import config
from code_steer_model_write.driver.halt import Halt
from code_steer_model_write.events import EventLog
from code_steer_model_write.recipes import registry
from code_steer_model_write.spec.events import Event
from code_steer_model_write.state.run import RunPaths, RunState, runner_alive

from . import timeline
from .timeline import TimelineRow


def _fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _hhmm(ts: datetime | None) -> str:
    return ts.astimezone().strftime("%H:%M") if ts else "–"


def _k(n: int) -> str:
    return f"{n / 1000:.0f}K" if n >= 1000 else str(n)


class StageView(BaseModel):
    id: str
    n: int
    title: str
    emoji: str
    hue: str
    description: str
    author: str
    checker: str
    state: str  # pending | now | done | halted
    duration: str
    rounds: str = ""
    tokens: dict[str, int] = Field(default_factory=dict)
    note: str = ""
    started: datetime | None = None
    ended: datetime | None = None
    steps: list[str] = Field(default_factory=list)
    outcome: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=list)
    gate: dict[str, Any] | None = None  # the open gate's ask record, if any


class Chip(BaseModel):
    key: str
    label: str
    count: int
    tone: str  # warn | bad | live
    stage: str | None = None


class StepRow(BaseModel):
    """One step of the run as the page lists it: done, running, or pending (derived from disk but
    not yet issued). Pending steps show which side and model the run will wait for."""

    step: str
    stage: str
    kind: str
    role: str  # author | checker | code | you
    model: str
    status: str  # done | running | pending | waiting
    tokens: int = 0
    seconds: float = 0.0


class AgentRun(BaseModel):
    step: str
    role: str
    model: str
    attempt: int
    seconds: float
    tokens: int
    status: str
    stage: str


class Segment(BaseModel):
    lane: str  # a | b | you | code
    label: str
    start: float
    end: float
    stage: str
    kind: str = "call"


class ArtifactRef(BaseModel):
    stage: str
    label: str  # "contract v3", "review r1 · findings", "gate blocks.r1 · decision"
    path: str  # run-dir relative
    kind: str  # artifact | findings | arbitration | gate | ruling | results | report


class RunView(BaseModel):
    run_id: str
    recipe: str
    mode: str
    rounds: int
    models: dict[str, str]
    sides: dict[str, str]
    fresh: bool
    resumed_count: int
    last_halt: str | None
    status: str
    outcome: str | None
    process: str  # running | completed | halted honestly | broke | waiting
    product: str
    started_at: datetime | None
    completed_at: datetime | None
    elapsed: str
    remaining: str
    tokens: dict[str, int]
    cost: dict[str, str] = {}  # per side, '$0.12' or '$?' when the price is unknown (rule 14)
    cost_total: str = ""
    cost_note: str = ""  # "at API rates" when a side ran on a CLI login: the subscription bills flat
    now_word: str
    now_text: str
    now_role: str | None
    stages: list[StageView]
    current_stage: str | None
    chips: list[Chip]
    agent_runs: list[AgentRun]
    steps: list[StepRow] = []
    segments: list[Segment]
    timeline: list[TimelineRow] = Field(default_factory=list)  # §7d piece 2: one row per step
    token_series: dict[str, list[tuple[float, int]]]
    events: list[dict[str, Any]]
    carried: list[dict[str, Any]]
    flagged: list[str]
    report_md: str | None
    refresh_hash: str
    live_files: list[str]
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    control: str = "queued"  # running | stopping | gate | halted | stale | broke | queued | done
    control_label: str = ""
    control_verb: str = ""  # stop | answer | resume | start | report | ""
    control_tone: str = "neutral"
    progress: float = 0.0  # 0..1 end to end: done stages plus the running stage's steps done
    stage_progress: list[float] = Field(default_factory=list)  # per stage, 0..1, in rail order
    dot: str = "queued"  # running | waiting | halted | done | queued
    dot_ring: str = ""  # "" | ok | warn  (for done: clean verdict, or carried items)


def refresh_hash(paths: RunPaths) -> tuple[str, list[str]]:
    """Every live file's size and mtime; a reload on any change, on nothing else (§7a rule 27)."""
    files: list[Path] = [paths.state, paths.events, paths.halt, paths.decisions, paths.task]
    files += sorted(
        p for p in paths.run_dir.iterdir() if p.is_file() and p.suffix in (".json", ".md", ".filled")
    )
    for d in (
        paths.gates,
        paths.streams,
        paths.artifacts,
        paths.run_dir / "review",
        paths.run_dir / "triage",
    ):
        if d.exists():
            files += sorted(p for p in d.rglob("*") if p.is_file())
    h = hashlib.sha256()
    live: list[str] = []
    for f in files:
        if f.exists():
            st = f.stat()
            h.update(f"{f}:{st.st_size}:{st.st_mtime_ns}\n".encode())
            live.append(str(f.relative_to(paths.run_dir)))
    return h.hexdigest()[:16], live


def build_view(run_dir: Path | str) -> RunView:
    paths = RunPaths(run_dir=Path(run_dir))
    st = RunState.load(paths)
    recipe = registry.get(st.recipe)
    spec = recipe.spec
    log = EventLog(paths.events, st.run_id)
    evs = log.all()
    halt = Halt.read(paths)
    sides = {r: s for r, s in spec.roles.items()}
    models = {r: st.task.roles[r].model for r in spec.roles if r in st.task.roles}
    t0 = evs[0].ts if evs else st.created_at
    t_end = st.completed_at or (evs[-1].ts if evs else t0)
    now = datetime.now(timezone.utc)
    stale = st.status.value == "RUNNING" and not runner_alive(paths)
    running = st.status.value == "RUNNING" and not stale
    elapsed_s = ((now if running else t_end) - t0).total_seconds()

    # ---- per-step facts from the events -------------------------------------------------
    step_phase: dict[str, str] = {}
    step_start: dict[str, datetime] = {}
    step_end: dict[str, datetime] = {}
    step_role: dict[str, str] = {}
    step_status: dict[str, str] = {}
    calls: dict[tuple[str, int], dict[str, Any]] = {}
    tokens_by_role: dict[str, int] = {}
    io_by_role: dict[str, list[int]] = {}
    series: dict[str, list[tuple[float, int]]] = {}
    refused = 0
    halts = 0
    retries = 0
    gate_asked: dict[str, Event] = {}
    for e in evs:
        if e.kind == "step.issued" and e.step:
            step_phase[e.step] = str(e.data.get("phase", step_phase.get(e.step, "")))
        elif e.kind == "step.started" and e.step:
            step_start[e.step] = e.ts
            step_status[e.step] = "now"
        elif e.kind == "step.done" and e.step:
            step_end[e.step] = e.ts
            step_status[e.step] = "done"
        elif e.kind == "call.started" and e.step:
            step_role[e.step] = e.role or ""
            calls[(e.step, e.attempt or 1)] = {
                "step": e.step,
                "role": e.role or "",
                "model": e.data.get("model", ""),
                "attempt": e.attempt or 1,
                "t0": e.ts,
                "t1": None,
                "tokens": 0,
                "status": "running",
            }
        elif e.kind == "call.usage" and e.step:
            c = calls.get((e.step, e.attempt or 1))
            n = int(e.data.get("input_tokens", 0)) + int(e.data.get("output_tokens", 0))
            if c:
                c["tokens"] += n
            if e.role:
                tokens_by_role[e.role] = tokens_by_role.get(e.role, 0) + n
                io = io_by_role.setdefault(e.role, [0, 0, 0])
                io[0] += int(e.data.get("input_tokens", 0))
                io[1] += int(e.data.get("output_tokens", 0))
                io[2] += int(e.data.get("cache_read_tokens", 0))
                series.setdefault(e.role, []).append(((e.ts - t0).total_seconds(), tokens_by_role[e.role]))
        elif e.kind in ("call.final", "call.error") and e.step:
            c = calls.get((e.step, e.attempt or 1))
            if c:
                c["t1"] = e.ts
                c["status"] = "ok" if e.kind == "call.final" else str(e.data.get("status", "error"))
        elif e.kind == "step.refused":
            refused += 1
        elif e.kind == "halt":
            halts += 1
            if e.step:
                step_status[e.step] = "halted"
        elif e.kind == "gate.asked" and e.step:
            gate_asked[e.step] = e
        elif e.kind == "call.error" and e.data.get("status") in ("stall",):
            retries += 1

    # ---- stages ----------------------------------------------------------------------------
    by_phase: dict[str, list[str]] = {}
    for k, ph in step_phase.items():
        by_phase.setdefault(ph, []).append(k)
    stages: list[StageView] = []
    current: str | None = None
    last_done_stage: str | None = None
    for s in spec.stages:
        keys = by_phase.get(str(s.n), [])
        starts = [step_start[k] for k in keys if k in step_start]
        ends = [step_end[k] for k in keys if k in step_end]
        statuses = [step_status.get(k, "pending") for k in keys]
        if not keys:
            state = "pending"
        elif "halted" in statuses:
            state = "halted"
        elif (
            all(x == "done" for x in statuses)
            and st.status.value == "COMPLETED"
            or (all(x == "done" for x in statuses) and any(step_phase.get(k) > str(s.n) for k in step_phase))
        ):
            state = "done"
        elif all(x == "done" for x in statuses) and not running:
            state = "done"
        else:
            state = "now"
        started = min(starts) if starts else None
        ended = max(ends) if ends and state == "done" else None
        if state == "now" and started and running:
            dur = _fmt_dur((now - started).total_seconds())
        elif started and (ended or ends):
            dur = _fmt_dur(((ended or max(ends)) - started).total_seconds())
        else:
            dur = ""
        toks: dict[str, int] = {}
        for (k, _a), c in calls.items():
            if k in keys and c["role"]:
                toks[c["role"]] = toks.get(c["role"], 0) + c["tokens"]
        rounds = ""
        rk = [
            int(k.rsplit("-review-r", 1)[1])
            for k in keys
            if "-review-r" in k and "audit" not in k and k in step_end
        ]
        if rk:
            rounds = f"Round {min(max(rk), st.task.rounds)}/{st.task.rounds}"
        note = _stage_note(s.id, paths, st)
        gate = None
        for k in keys:
            if k in gate_asked and step_status.get(k) != "done":
                g = gate_asked[k].data.get("gate")
                ask = paths.gates / f"{g}.ask.json"
                if ask.exists() and not (paths.gates / f"{g}.decision.json").exists():
                    gate = json.loads(ask.read_text())
        stages.append(
            StageView(
                id=s.id,
                n=s.n,
                title=s.title,
                emoji=s.emoji,
                hue=s.hue,
                description=s.description,
                author=s.author,
                checker=s.checker,
                state=state,
                duration=dur,
                rounds=rounds,
                tokens=toks,
                note=note,
                started=started,
                ended=ended,
                steps=keys,
                outcome=_stage_outcome(s.id, paths, st, note),
                rows=_stage_rows(s.id, paths),
                gate=gate,
            )
        )
        if state in ("now", "halted") and current is None:
            current = s.id
        if state == "done":
            last_done_stage = s.id
    if current is None:
        current = last_done_stage or (stages[0].id if stages else None)

    # ---- process, product, now line ----------------------------------------------------------
    if stale:
        process = "stale"
    elif st.status.value == "COMPLETED":
        process = "completed"
    elif st.status.value == "PAUSED":
        process = "halted honestly"
    elif st.status.value == "FAILED":
        process = "broke"
    elif running:
        process = "running"
    else:
        process = "waiting"
    report = None
    rp = paths.artifacts / "report" / "v001.json"
    product = "not yet"
    if rp.exists():
        report = json.loads(rp.read_text())
        product = report.get("verdict", "")
    now_word, now_text, now_role = _now_line(st, evs, halt, stages, process, product, elapsed_s)

    chips: list[Chip] = []
    carried = [c.model_dump(mode="json") for c in st.carried]
    if carried:
        chips.append(Chip(key="carried", label="Carried", count=len(carried), tone="warn"))
    failing = 0
    res = paths.artifacts / "results"
    if res.exists():
        vs = sorted(res.glob("v*.json"))
        if vs:
            r = json.loads(vs[-1].read_text())
            failing = sum(1 for p in r["properties"] if p["real"] != "pass")
    if failing:
        chips.append(
            Chip(key="failing", label="Failing properties", count=failing, tone="bad", stage="verify")
        )
    if halts:
        chips.append(Chip(key="halts", label="Halts", count=halts, tone="bad"))
    if refused:
        chips.append(Chip(key="refused", label="Refused, re-asked", count=refused, tone="warn"))
    if retries:
        chips.append(Chip(key="retries", label="Stalls", count=retries, tone="warn"))

    steps = _step_rows(paths, st, spec, calls, step_phase, now)
    agent_runs = [
        AgentRun(
            step=c["step"],
            role=c["role"],
            model=c["model"],
            attempt=c["attempt"],
            seconds=round(((c["t1"] or now) - c["t0"]).total_seconds(), 1),
            tokens=c["tokens"],
            status=c["status"],
            stage=_stage_of(step_phase.get(c["step"], ""), spec),
        )
        for c in calls.values()
    ]
    segments = [
        Segment(
            lane=sides.get(c["role"], "code"),
            label=c["step"],
            start=(c["t0"] - t0).total_seconds(),
            end=((c["t1"] or now) - t0).total_seconds(),
            stage=_stage_of(step_phase.get(c["step"], ""), spec),
        )
        for c in calls.values()
    ]
    for e in evs:
        if e.kind == "gate.decided":
            segments.append(
                Segment(
                    lane="you",
                    label=str(e.data.get("gate")),
                    start=(e.ts - t0).total_seconds(),
                    end=(e.ts - t0).total_seconds(),
                    stage=_stage_of(step_phase.get(e.step or "", ""), spec),
                    kind="decision" if e.data.get("source") == "human" else "auto",
                )
            )
    ev_rows = [
        {
            "seq": e.seq,
            "time": _hhmm(e.ts),
            "phase": step_phase.get(e.step or "", ""),
            "kind": e.kind,
            "step": e.step or "",
            "text": _event_text(e),
        }
        for e in evs
    ]
    fl = []
    if paths.decisions.exists():
        fl = [d["id"] for d in json.loads(paths.decisions.read_text()) if d.get("flagged")]
    rh, live = refresh_hash(paths)
    rmd = (paths.run_dir / "REPORT.md").read_text() if (paths.run_dir / "REPORT.md").exists() else None
    dot, ring = run_dot(st, halt, any(s.gate for s in stages), bool(carried) or failing > 0, stale=stale)
    ctl = run_control(
        st, halt, any(s.gate for s in stages), stale=stale, stop_requested=(paths.run_dir / "STOP").exists()
    )
    fracs: list[float] = []
    for sv in stages:
        if sv.state == "done" or st.status.value == "COMPLETED":
            fracs.append(1.0)
        elif sv.steps:
            done_n = sum(1 for k in sv.steps if step_status.get(k) == "done")
            fracs.append(min(0.95, done_n / max(len(sv.steps) + 1, 1)))
        else:
            fracs.append(0.0)
    progress = round(sum(fracs) / max(len(fracs), 1), 3) if fracs else 0.0
    cost_by_role = {
        r: config.cost_usd(models.get(r, ""), io[0], io[1], io[2]) for r, io in io_by_role.items()
    }
    arts = list_artifacts(paths, spec, step_phase, evs)
    return RunView(
        run_id=st.run_id,
        recipe=st.recipe,
        mode=st.task.mode.value,
        rounds=st.task.rounds,
        models=models,
        sides=sides,
        fresh=st.resumed_count == 0,
        resumed_count=st.resumed_count,
        last_halt=st.last_halt,
        status=st.status.value,
        outcome=st.outcome.value if st.outcome else None,
        process=process,
        product=product,
        started_at=t0,
        completed_at=st.completed_at,
        elapsed=_fmt_dur(elapsed_s),
        remaining="steps" if running else "",
        tokens=tokens_by_role,
        cost={r: config.usd(cost_by_role[r]) for r in cost_by_role},
        cost_total=config.usd(
            sum(cost_by_role.values())
            if cost_by_role and all(v is not None for v in cost_by_role.values())
            else None
        ),
        cost_note=_cost_note(paths),
        now_word=now_word,
        now_text=now_text,
        now_role=now_role,
        stages=stages,
        current_stage=current,
        chips=chips,
        agent_runs=agent_runs,
        steps=steps,
        segments=segments,
        timeline=[
            r.model_copy(update={"lane": sides.get(r.role, "code") if r.role else "code"})
            for r in timeline.rows(evs, now=now)
        ],
        token_series=series,
        events=ev_rows,
        carried=carried,
        flagged=fl,
        report_md=rmd,
        refresh_hash=rh,
        live_files=live,
        artifacts=arts,
        dot=dot,
        dot_ring=ring,
        progress=progress,
        stage_progress=fracs,
        control=ctl[0],
        control_label=ctl[1],
        control_verb=ctl[2],
        control_tone=ctl[3],
    )


def run_control(
    st: RunState, halt: Halt | None, gated: bool, *, stale: bool, stop_requested: bool
) -> tuple[str, str, str, str]:
    """The run-status control (docs/DASHBOARD-DESIGN.md): (state, label, verb, tone). One owner
    for what the bottom bar's button says and does."""
    status = st.status.value
    if status == "COMPLETED":
        return "done", "DONE", "report", "neutral"
    if status == "FAILED" or (halt is not None and not halt.resumable):
        return "broke", "BROKE", "", "bad"
    if stale:
        return "stale", "STALE · RESUME", "resume", "bad"
    if status in ("PAUSED", "CANCELLED") or halt is not None:
        return "halted", "HALTED · RESUME", "resume", "bad"
    if status == "RUNNING" and stop_requested:
        return "stopping", "STOPPING…", "", "ok"
    if status == "RUNNING" and gated:
        return "gate", "GATE · ANSWER", "answer", "warn"
    if status == "RUNNING":
        return "running", "RUNNING · STOP", "stop", "ok"
    return "queued", "QUEUED · START", "start", "neutral"


def run_dot(
    st: RunState, halt: Halt | None, gated: bool, unclean: bool, *, stale: bool = False
) -> tuple[str, str]:
    """The runs-tab dot: green running, amber waiting for you, red halted, broke or stale, grey done."""
    if stale or st.status.value in ("PAUSED", "FAILED", "CANCELLED") or halt is not None:
        return "halted", ""
    if st.status.value == "COMPLETED":
        return "done", ("warn" if unclean else "ok")
    if gated:
        return "waiting", ""
    if st.status.value == "RUNNING":
        return "running", ""
    return "queued", ""


def list_artifacts(
    paths: RunPaths, spec, step_phase: dict[str, str], events: list[Event] | None = None
) -> list[ArtifactRef]:
    """Every record a stage produced, in order, as a clickable reference; the page renders it
    as markdown on demand with the same renderer the models read (rule 2). Which stage owns an
    artifact is read from the `artifact.written` events (the step that wrote it and that step's
    phase), so no recipe has to be named here."""
    run = paths.run_dir
    out: list[ArtifactRef] = []
    first = spec.stages[0].id
    stage_of_key: dict[str, str] = {}
    for e in events or []:
        if e.kind != "artifact.written" or not e.step:
            continue
        parts = Path(str(e.data.get("path", ""))).parts
        if "artifacts" in parts and parts.index("artifacts") + 1 < len(parts):
            key = parts[parts.index("artifacts") + 1]
            stage_of_key.setdefault(key, _stage_of(step_phase.get(e.step, ""), spec) or first)

    def loop_stage(loop: str) -> str:  # a review loop is named after the artifact it attacks
        return stage_of_key.get(loop) or stage_of_key.get(loop.split("_")[0], first)

    stages = {s.id for s in spec.stages}
    if paths.artifacts.exists():
        for d in sorted(paths.artifacts.iterdir()):
            st = stage_of_key.get(d.name, spec.stages[0].id)
            if st not in stages:
                st = spec.stages[0].id
            for v in sorted(d.glob("v*.json")):
                out.append(
                    ArtifactRef(
                        stage=st, label=f"{d.name} {v.stem}", path=str(v.relative_to(run)), kind="artifact"
                    )
                )
    rev = run / "review"
    if rev.exists():
        for loop in sorted(rev.iterdir()):
            st = loop_stage(loop.name)
            for f in sorted(loop.glob("round-*.findings.json")):
                n = f.name.split("-")[1].split(".")[0]
                out.append(
                    ArtifactRef(
                        stage=st,
                        label=f"{loop.name} r{n} · findings",
                        path=str(f.relative_to(run)),
                        kind="findings",
                    )
                )
                a = loop / f"round-{n}.arbitration.json"
                if a.exists():
                    out.append(
                        ArtifactRef(
                            stage=st,
                            label=f"{loop.name} r{n} · arbitration",
                            path=str(a.relative_to(run)),
                            kind="arbitration",
                        )
                    )
    if paths.gates.exists():
        for g in sorted(paths.gates.glob("*.ask.json")):
            gid = g.name[: -len(".ask.json")]
            stg = next(
                (s.id for s in spec.stages for x in s.gates_after if gid.startswith(x)), spec.stages[0].id
            )
            out.append(
                ArtifactRef(stage=stg, label=f"gate {gid} · ask", path=str(g.relative_to(run)), kind="gate")
            )
            d = paths.gates / f"{gid}.decision.json"
            if d.exists():
                out.append(
                    ArtifactRef(
                        stage=stg, label=f"gate {gid} · decision", path=str(d.relative_to(run)), kind="gate"
                    )
                )
    tri = run / "triage"
    if tri.exists():
        for f in sorted(tri.glob("*.json")):
            out.append(
                ArtifactRef(
                    stage="verify", label=f"ruling {f.stem}", path=str(f.relative_to(run)), kind="ruling"
                )
            )
    for name in ("freeze.json", "coverage.json", "evals.json"):
        p = run / name
        if p.exists():
            out.append(
                ArtifactRef(
                    stage={
                        "freeze.json": "contracts",
                        "coverage.json": "verification",
                        "evals.json": "verify",
                    }.get(name, spec.stages[0].id),
                    label=name,
                    path=name,
                    kind="artifact",
                )
            )
    return out


def render_artifact(run_dir: Path | str, rel: str) -> str:
    """The record at `rel`, as the markdown a model would read (rule 2). Lists of findings and
    plain JSON records get a table; an Artifact gets its own renderer."""
    from code_steer_model_write.artifacts.render import render as _render
    from code_steer_model_write.review.rounds import ReviewLoop
    from code_steer_model_write.spec.findings import Finding

    p = Path(run_dir) / rel
    if not p.exists():
        return "(gone)"
    data = json.loads(p.read_text())
    if isinstance(data, list) and data and isinstance(data[0], dict) and "severity" in data[0]:
        return ReviewLoop.render_findings([Finding.model_validate(x) for x in data], audience="human")
    model = _model_for(rel)
    if model is not None:
        try:
            return _render(model.model_validate(data), "human")
        except Exception:  # noqa: BLE001 -- fall through to the generic table
            pass
    return _generic_md(data)


def _model_for(rel: str):
    from code_steer_model_write.artifacts.brief import Brief
    from code_steer_model_write.artifacts.contract import Contract
    from code_steer_model_write.artifacts.ledger import AssumptionsLedger
    from code_steer_model_write.artifacts.plan import Plan
    from code_steer_model_write.artifacts.report import Report
    from code_steer_model_write.artifacts.results import Results, Ruling
    from code_steer_model_write.artifacts.tasks import Tasks
    from code_steer_model_write.artifacts.vspec import VerificationSpec

    parts = Path(rel).parts
    if parts[0] == "artifacts":
        return {
            "brief": Brief,
            "ledger": AssumptionsLedger,
            "plan": Plan,
            "contract": Contract,
            "vspec": VerificationSpec,
            "tasks": Tasks,
            "results": Results,
            "report": Report,
        }.get(parts[1])
    if parts[0] == "triage":
        return Ruling
    return None


def _generic_md(data: Any, level: int = 3) -> str:
    if isinstance(data, dict):
        rows = []
        nested = []
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                nested.append((k, v))
            else:
                rows.append(
                    f"| {k} | {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v.replace(chr(10), ' ')} |"
                )
        out = ["| field | value |", "|---|---|", *rows] if rows else []
        for k, v in nested:
            out.append(f"\n{'#' * level} {k}\n")
            out.append(_generic_md(v, level + 1))
        return "\n".join(out)
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data):
            cols = list(dict.fromkeys(k for x in data for k in x))
            lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            for x in data:
                lines.append(
                    "| "
                    + " | ".join(str(x.get(c, "")).replace("|", "/").replace("\n", " ")[:200] for c in cols)
                    + " |"
                )
            return "\n".join(lines)
        return "\n".join(f"- {x}" for x in data) or "(empty)"
    return str(data)


def _step_rows(
    paths: RunPaths, st: RunState, spec, calls: dict, step_phase: dict[str, str], now
) -> list[StepRow]:
    """The steps the recipe derives from disk right now (rule 1: steps come from files), each
    with its status from state.json and its tokens from the calls. A step not yet issued is
    pending; its side and model come from the task, per-stage settings included."""
    from code_steer_model_write import settings_form as sf
    from code_steer_model_write.artifacts.store import Store
    from code_steer_model_write.spec.task import TaskSpec

    task = None
    tp = paths.run_dir / "task.json"
    if tp.exists():
        try:
            task = TaskSpec.model_validate(json.loads(tp.read_text()))
        except Exception:  # noqa: BLE001 - an unreadable task only costs the pending rows their model
            task = None
    try:
        program_steps = registry.get(st.recipe).steps(st, paths, Store(paths.run_dir))
    except Exception:  # noqa: BLE001 - a recipe that cannot derive from a half-written run dir
        program_steps = []
    by_step: dict[str, dict] = {}
    for (key, _attempt), c in calls.items():
        row = by_step.setdefault(key, {"tokens": 0, "seconds": 0.0, "model": "", "role": ""})
        row["tokens"] += c["tokens"]
        row["seconds"] += ((c["t1"] or now) - c["t0"]).total_seconds()
        row["model"] = c["model"] or row["model"]
        row["role"] = c["role"] or row["role"]
    out: list[StepRow] = []
    seen: set[str] = set()
    for sp in program_steps:
        seen.add(sp.key)
        rec = st.steps.get(sp.key)
        status = "done" if rec and rec.done_at is not None else ("running" if rec else "pending")
        role = sp.role or ("you" if sp.gate else "code")
        stage = _stage_of(str(sp.phase), spec) or (spec.stages[0].id if spec.stages else "")
        model = by_step.get(sp.key, {}).get("model", "")
        if not model and task is not None and role in task.roles:
            try:
                model = sf.stage_role(task, stage, role).model
            except Exception:  # noqa: BLE001
                model = task.roles[role].model
        c = by_step.get(sp.key, {})
        out.append(
            StepRow(
                step=sp.key,
                stage=stage,
                kind=sp.kind.value,
                role=role,
                model=model or "",
                status=status,
                tokens=int(c.get("tokens", 0)),
                seconds=round(float(c.get("seconds", 0.0)), 1),
            )
        )
    for key, c in by_step.items():  # a call the recipe no longer lists (an old round): still shown
        if key not in seen:
            rec = st.steps.get(key)
            out.append(
                StepRow(
                    step=key,
                    stage=_stage_of(step_phase.get(key, ""), spec),
                    kind="author",
                    role=c["role"] or "code",
                    model=c["model"],
                    status="done" if rec and rec.done_at is not None else "running",
                    tokens=int(c["tokens"]),
                    seconds=round(float(c["seconds"]), 1),
                )
            )
    return out


def _cost_note(paths: RunPaths) -> str:
    """The estimate is the API price of the tokens. A CLI backend on a subscription login is not
    billed per token, so the page says so beside the figure rather than presenting it as a bill."""
    tp = paths.run_dir / "task.json"
    if not tp.exists():
        return ""
    try:
        roles = json.loads(tp.read_text()).get("roles") or {}
    except ValueError:
        return ""
    backends = {str((r or {}).get("backend", "")) for r in roles.values()}
    return "at API rates" if backends & {"claude_cli", "codex_cli"} else ""


def _stage_of(phase: str, spec) -> str:
    for s in spec.stages:
        if str(s.n) == phase:
            return s.id
    return ""


def _now_line(
    st: RunState,
    evs: list[Event],
    halt: Halt | None,
    stages: list[StageView],
    process: str,
    product: str,
    elapsed: float,
):
    if process == "stale":
        last_step = next((e.step for e in reversed(evs) if e.step), None)
        return (
            "STALE",
            f"The runner process is gone while the record says running · last step {last_step} · Resume continues from disk",
            None,
        )
    if process == "completed":
        return "COMPLETE", f"Run complete · {product} · {_fmt_dur(elapsed)}", None
    if halt is not None:
        return (
            "HALT",
            f"{halt.step} · {halt.reason.value} · {halt.message[:160]}"
            + (" · Resume continues here" if halt.resumable else ""),
            None,
        )
    for s in stages:
        if s.gate is not None:
            return "GATE", f"{s.gate.get('title', 'a decision')} · answer on the page to continue", None
    last = None
    for e in reversed(evs):
        if e.kind in ("step.started", "call.started", "gate.asked", "step.done"):
            last = e
            break
    if last is None:
        return "QUEUED", "waiting to start", None
    role = last.role
    return "RUNNING", f"{last.step} · {last.kind.split('.')[1]}" + (f" · {role}" if role else ""), role


def _stage_note(stage_id: str, paths: RunPaths, st: RunState) -> str:
    run = paths.run_dir
    try:
        if stage_id == "contracts" and (run / "freeze.json").exists():
            f = json.loads((run / "freeze.json").read_text())
            return f"Frozen v{f['version']} · {f['clauses']} clauses · sha {f['sha_full'][:8]}"
        if stage_id == "plan":
            p = run / "review" / "plan"
            if p.exists():
                n = len(list(p.glob("round-*.findings.json")))
                fs = sum(len(json.loads(x.read_text())) for x in p.glob("round-*.findings.json"))
                return f"{n} round(s) · {fs} finding(s)"
        if stage_id == "verification":
            c = run / "coverage.json"
            if c.exists():
                cov = json.loads(c.read_text())
                return f"{len(cov['cited'])}/{len(cov['checkable'])} clauses cited" + (
                    f" · {len(cov['uncovered'])} uncovered" if cov["uncovered"] else ""
                )
        if stage_id == "build":
            m = run / "build" / "manifest.json"
            if m.exists():
                return f"{len(json.loads(m.read_text()))} tests mapped"
        if stage_id == "verify":
            res = (
                sorted((paths.artifacts / "results").glob("v*.json"))
                if (paths.artifacts / "results").exists()
                else []
            )
            if res:
                r = json.loads(res[-1].read_text())
                passed = sum(1 for p in r["properties"] if p["real"] == "pass")
                nulls = sum(1 for p in r["properties"] if p["null"] == "fail")
                return f"{passed}/{len(r['properties'])} pass · {nulls} fail on the null"
    except Exception:  # noqa: BLE001 -- a note is a courtesy, never a crash
        return ""
    return ""


def _stage_outcome(stage_id: str, paths: RunPaths, st: RunState, note: str) -> str:
    if stage_id == "verify" and note:
        return f"Run complete: {note}"
    return note


def _stage_rows(stage_id: str, paths: RunPaths) -> list[dict[str, Any]]:
    if stage_id == "verify":
        res = (
            sorted((paths.artifacts / "results").glob("v*.json"))
            if (paths.artifacts / "results").exists()
            else []
        )
        if not res:
            return []
        r = json.loads(res[-1].read_text())
        vs = paths.artifacts / "vspec"
        desc: dict[str, str] = {}
        if vs.exists():
            v = json.loads(sorted(vs.glob("v*.json"))[-1].read_text())
            desc = {p["id"]: p["falsifies"] for p in v["properties"]}
        return [
            {
                "id": p["property"],
                "text": desc.get(p["property"], p["test"]),
                "verdict": p["real"],
                "count": f"{p['passes']}/{p['runs']}",
                "null": p["null"],
            }
            for p in r["properties"]
        ]
    if stage_id in ("plan", "contracts", "verification"):
        key = {"plan": "plan", "contracts": "contract", "verification": "vspec"}[stage_id]
        d = paths.run_dir / "review" / key
        rows: list[dict[str, Any]] = []
        if d.exists():
            for f in sorted(d.glob("round-*.findings.json")):
                for x in json.loads(f.read_text()):
                    rows.append(
                        {
                            "id": x.get("id"),
                            "text": x.get("argument", "")[:160],
                            "verdict": x.get("status"),
                            "count": x.get("severity"),
                            "null": x.get("klass"),
                        }
                    )
        return rows
    return []


def _event_text(e: Event) -> str:
    d = e.data
    k = e.kind
    if k == "run.status":
        return f"Run {d.get('status', '').lower()}" + (f": {d.get('message')}" if d.get("message") else "")
    if k == "step.issued":
        return f"Issued {e.step}" + (" (reopened: deliverable missing)" if d.get("reopened") else "")
    if k == "step.started":
        return f"Started {e.step} (attempt {e.attempt})"
    if k == "step.done":
        return f"Done {e.step}: {len(d.get('deliverables', []))} deliverable(s)"
    if k == "call.started":
        return f"{e.role} call · {d.get('model')} · {d.get('schema')}"
    if k == "call.usage":
        return f"{int(d.get('input_tokens', 0)) + int(d.get('output_tokens', 0))} tok"
    if k == "call.final":
        return f"answer in ({d.get('tokens', '')} tok)"
    if k == "check.result":
        p = d.get("problems", [])
        return "checks pass" if not p else f"{len(p)} problem(s): {p[0][:100]}"
    if k == "step.refused":
        return f"refused, re-asked: {(d.get('problems') or [''])[0][:100]}"
    if k == "gate.asked":
        return f"Gate {d.get('gate')}: {d.get('title')} ({'you' if d.get('needs_human') else 'auto'})"
    if k == "gate.decided":
        return f"Gate {d.get('gate')} {d.get('action')} by {d.get('source')}" + (
            f", flagged {d.get('flagged')}" if d.get("flagged") else ""
        )
    if k == "finding.filed":
        return f"{d.get('id')} filed: {d.get('severity')}/{d.get('klass')} on {', '.join(d.get('cites', []))}"
    if k == "finding.decided":
        return f"{d.get('id')} {d.get('status')}"
    if k == "round.closed":
        return (
            f"Round {d.get('round')} {d.get('verdict')}: {d.get('findings')} finding(s)"
            + (" · converged" if d.get("converged") else "")
            + (" · closing read" if d.get("closing") else "")
        )
    if k == "artifact.written":
        return f"wrote {d.get('path')}"
    if k == "judge.verdict":
        return f"{d.get('property')} q{d.get('question')}: {d.get('verdict')}"
    if k == "halt":
        return f"HALT {d.get('reason')}: {d.get('message', '')[:120]}"
    if k == "decision.auto":
        return f"auto-answered, flagged: {d.get('flagged')}"
    return json.dumps(d)[:120]
