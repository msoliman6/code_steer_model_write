"""The Reflex page (docs/PLAN.md §7, §7a). It renders the view model and nothing else: every
number comes from `model.build_view`, every colour from `theme`. Four zones: the constant
header (identity, rail, clock, NOW line, chips), the selected stage's panel with the gate form
inline, the stage's evidence, the run's evidence. A 3 s poller reloads the model only when the
refresh hash moved; the picked stage survives it (session storage)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
from pathlib import Path
from typing import Any

import reflex as rx

from code_steer_model_write.gates.gate import write_decision
from code_steer_model_write.spec.decisions import Decision, GateDecision
from code_steer_model_write.state.lock import atomic_write_text
from code_steer_model_write.state.run import RunPaths

from . import home, theme as T
from .glyphs import side_mark
from .model import build_view, render_artifact
from .start import start_page

RUNS_DIR = Path(os.environ.get("CSMW_RUNS_DIR", "runs"))


def _settings_rows(run_dir: str) -> list["SettingRow"]:
    """What the run was started with: the form's values when the run came from the start page,
    else the task's roles, mode and rounds (rule 4: one record, rendered)."""
    from code_steer_model_write import settings_form as sf

    task = (
        json.loads((Path(run_dir) / "task.json").read_text())
        if (Path(run_dir) / "task.json").exists()
        else {}
    )
    form = (task.get("metadata") or {}).get("form")
    rows: list[SettingRow] = []
    if form:
        for f in sf.FIELDS:
            v = form.get(f.key, "")
            if v:
                rows.append(SettingRow(name=f.name[:1].upper() + f.name[1:], value=str(v), group=f.group))
        return rows
    rows.append(
        SettingRow(
            name="request",
            value=(task.get("inputs", {}).get("brief", {}) or {}).get("request", ""),
            group="brief",
        )
    )
    rows.append(SettingRow(name="running mode", value=str(task.get("mode", "")), group="settings"))
    rows.append(SettingRow(name="attack rounds", value=str(task.get("rounds", "")), group="settings"))
    for role, spec in (task.get("roles") or {}).items():
        rows.append(SettingRow(name=f"{role} backend", value=spec.get("backend", ""), group="settings"))
        rows.append(SettingRow(name=f"{role} model", value=spec.get("model", ""), group="settings"))
        rows.append(SettingRow(name=f"{role} effort", value=spec.get("effort", ""), group="settings"))
    return rows


def _registry():
    """The Run Registry (ARCHITECTURE.md L2/L7): one index across every runs directory. This
    page's own runs directory is always registered, so a run started by hand is not lost."""
    from code_steer_model_write.layers.registry import RunRegistry

    reg = RunRegistry()
    if RUNS_DIR.exists():
        reg.add_dir(RUNS_DIR)
    return reg


def _runs() -> list[dict[str, str]]:
    """The tab strip's list from the registry: every run in every registered runs directory,
    newest first; the dot from each run's own files (the registry is an index, not the record)."""
    reg = _registry()
    reg.scan()
    out = []
    rows = sorted(
        reg.refresh(),
        key=lambda r: Path(r["run_dir"]).stat().st_mtime if Path(r["run_dir"]).exists() else 0,
        reverse=True,
    )
    for r in rows:
        d = Path(r["run_dir"])
        if not (d / "state.json").exists():
            continue
        st = json.loads((d / "state.json").read_text())
        dot, ring = home.run_dot(d, st)
        out.append(
            {
                "id": st["run_id"],
                "recipe": st["recipe"],
                "status": st["status"],
                "dir": str(d),
                "dot": dot,
                "ring": ring,
            }
        )
    return out


def _eval_rows(run_dir: str) -> tuple[list[EvalRow], str]:
    """The Evals tab's rows from `evals.json` (ARCHITECTURE.md 7.9): the record the runtime's
    Evaluator wrote at completion. Absent until then."""
    p = Path(run_dir) / "evals.json"
    if not p.exists():
        return [], ""
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return [], "evals.json is not JSON"
    rows: list[EvalRow] = []
    for r in d.get("results", []):
        v = r.get("value")
        t = r.get("target")
        rows.append(
            EvalRow(
                metric=r.get("metric", ""),
                value="—"
                if v is None
                else (f"{v:.2f}" if isinstance(v, float) and not float(v).is_integer() else str(int(v))),
                target=""
                if t is None
                else (f"{t:.2f}" if isinstance(t, float) and not float(t).is_integer() else str(int(t))),
                passed="" if r.get("passed") is None else ("pass" if r.get("passed") else "fail"),
                tier=r.get("tier", ""),
                note=r.get("note", ""),
            )
        )
    n_t = sum(1 for r in rows if r.passed)
    n_ok = sum(1 for r in rows if r.passed == "pass")
    return rows, (f"{n_ok}/{n_t} targets met" if n_t else f"{len(rows)} metrics, no targets")


# ---- typed rows (Reflex iterates typed lists only) ----------------------------------------


@dataclasses.dataclass
class TokenRow:
    role: str = ""
    n: int = 0
    label: str = ""  # K / M
    cost: str = ""


@dataclasses.dataclass
class ArtRow:
    stage: str = ""
    label: str = ""
    path: str = ""
    kind: str = ""


@dataclasses.dataclass
class EvalRow:
    metric: str = ""
    value: str = ""
    target: str = ""
    passed: str = ""  # "pass" | "fail" | "" (no target)
    tier: str = ""
    note: str = ""


@dataclasses.dataclass
class Row:
    id: str = ""
    text: str = ""
    verdict: str = ""
    count: str = ""
    null: str = ""


@dataclasses.dataclass
class Question:
    id: str = ""
    text: str = ""
    kind: str = "confirm"
    default: str = ""
    recommended: str = ""
    gloss: str = ""


@dataclasses.dataclass
class CarriedRow:
    id: str = ""
    kind: str = ""
    argument: str = ""
    summary: str = ""


@dataclasses.dataclass
class GateView:
    id: str = ""
    title: str = ""
    kind: str = "judgment"
    can_revise: bool = True
    questions: list[Question] = dataclasses.field(default_factory=list)
    carried: list[CarriedRow] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Stage:
    id: str = ""
    n: int = 0
    title: str = ""
    emoji: str = ""
    hue: str = "slate"
    description: str = ""
    author: str = ""
    checker: str = ""
    state: str = "pending"
    duration: str = ""
    rounds: str = ""
    note: str = ""
    outcome: str = ""
    tokens: list[TokenRow] = dataclasses.field(default_factory=list)
    rows: list[Row] = dataclasses.field(default_factory=list)
    has_gate: bool = False


@dataclasses.dataclass
class ChipRow:
    key: str = ""
    label: str = ""
    count: int = 0
    tone: str = "warn"


@dataclasses.dataclass
class StepRow:
    step: str = ""
    stage: str = ""
    kind: str = ""
    role: str = ""
    model: str = ""
    status: str = ""
    tokens: int = 0
    seconds: float = 0.0
    label: str = ""  # tokens in K/M


@dataclasses.dataclass
class AgentRow:
    step: str = ""
    role: str = ""
    model: str = ""
    attempt: int = 1
    seconds: float = 0.0
    tokens: int = 0
    status: str = ""
    stage: str = ""


@dataclasses.dataclass
class TLRow:
    step: str = ""
    kind: str = ""
    lane: str = "code"
    color: str = ""  # the lane's colour, resolved in Python (one owner: theme.ACTOR)
    left: float = 0.0
    width: float = 0.0
    call_left: float = 0.0
    call_width: float = 0.0
    has_call: bool = False
    label: str = ""  # tokens in K/M
    seconds: str = ""
    done: bool = True


@dataclasses.dataclass
class TLBand:
    stage: str = ""
    hue: str = "slate"
    left: float = 0.0
    width: float = 0.0


@dataclasses.dataclass
class TLTick:
    left: float = 0.0
    label: str = ""


@dataclasses.dataclass
class EventRow:
    seq: int = 0
    time: str = ""
    phase: str = ""
    kind: str = ""
    step: str = ""
    text: str = ""


@dataclasses.dataclass
class ModelRow:
    role: str = ""
    model: str = ""


@dataclasses.dataclass
class ProgRow:
    hue: str = "slate"
    frac: float = 0.0


@dataclasses.dataclass
class ProviderRow:
    backend: str = ""
    provider: str = ""
    pill: str = ""
    tone: str = "neutral"
    requirement: str = ""
    discovery: str = ""
    models: int = 0


@dataclasses.dataclass
class SettingRow:
    name: str = ""
    value: str = ""
    group: str = ""


def _gate_of(g: dict[str, Any] | None) -> GateView:
    if not g:
        return GateView()
    return GateView(
        id=g["id"],
        title=g.get("title", ""),
        kind=g.get("kind", "judgment"),
        can_revise=bool(g.get("can_revise", True)),
        questions=[
            Question(
                id=q["id"],
                text=q["text"],
                kind=q.get("kind", "confirm"),
                default=str(q.get("default") or ""),
                recommended=str(q.get("recommended") or ""),
                gloss=q.get("gloss", ""),
            )
            for q in g.get("questions", [])
        ],
        carried=[
            CarriedRow(
                id=str(c.get("id", "")),
                kind=str(c.get("kind", "")),
                argument=str(c.get("argument", c.get("summary", "")))[:200],
            )
            for c in g.get("carried", [])
        ],
    )


def _stage_of(s: dict[str, Any]) -> Stage:
    return Stage(
        id=s["id"],
        n=s["n"],
        title=s["title"],
        emoji=s["emoji"],
        hue=s["hue"],
        description=s["description"],
        author=s["author"],
        checker=s["checker"],
        state=s["state"],
        duration=s["duration"],
        rounds=s.get("rounds", ""),
        note=s.get("note", ""),
        outcome=s.get("outcome", ""),
        tokens=[TokenRow(role=k, n=v, label=T.k(v)) for k, v in s.get("tokens", {}).items()],
        rows=[
            Row(
                id=str(r.get("id", "")),
                text=str(r.get("text", "")),
                verdict=str(r.get("verdict", "")),
                count=str(r.get("count", "")),
                null=str(r.get("null", "")),
            )
            for r in s.get("rows", [])
        ],
        has_gate=bool(s.get("gate")),
    )


class S(rx.State):
    runs: list[dict[str, str]] = []
    run_dir: str = ""
    picked: str = rx.SessionStorage("", name="csmw_picked")
    loaded: bool = False
    hash_: str = ""
    answers: dict[str, str] = {}
    comments: dict[str, str] = {}
    detail_full: bool = False
    filter_phase: str = "all"
    view_tab: str = rx.SessionStorage("run", name="csmw_view")
    artifacts: list[ArtRow] = []
    evals: list[EvalRow] = []  # L8: the run's evals.json, the record; MLflow mirrors it
    evals_summary: str = ""
    open_paths: list[str] = []
    artifact_md: dict[str, str] = {}
    run_id: str = ""
    recipe: str = ""
    mode: str = ""
    rounds: int = 0
    fresh: bool = True
    resumed_count: int = 0
    last_halt: str = ""
    process: str = ""
    product: str = ""
    elapsed: str = ""
    remaining: str = ""
    now_word: str = ""
    now_text: str = ""
    current_stage: str = ""
    stages: list[Stage] = []
    gates: dict[str, GateView] = {}
    chips: list[ChipRow] = []
    agent_runs: list[AgentRow] = []
    steps: list[StepRow] = []
    hidden_runs: str = rx.LocalStorage("[]", name="csmw_hidden_runs")  # closed tabs, this browser
    timeline: list[TLRow] = []  # §7d piece 2
    tl_total: str = ""
    tl_bands: list[TLBand] = []  # one tinted band per stage, behind every row, in the stage's hue
    tl_ticks: list[TLTick] = []  # the time axis under the rows
    events: list[EventRow] = []
    carried: list[CarriedRow] = []
    model_rows: list[ModelRow] = []
    token_rows: list[TokenRow] = []
    cost_total: str = ""
    cost_note: str = ""
    flagged: list[str] = []
    report_md: str = ""
    settings_rows: list[SettingRow] = []
    providers: list[ProviderRow] = []
    progress: float = 0.0
    stage_progress: list[float] = []
    prog_rows: list[ProgRow] = []
    control: str = "queued"
    control_label: str = ""
    control_verb: str = ""
    control_tone: str = "neutral"
    ring: str = ""  # a finished run: "ok" clean, "warn" carried

    # ---- loading -------------------------------------------------------------------------

    def _apply(self, run_dir: str) -> None:
        v = build_view(run_dir)
        if v.refresh_hash == self.hash_:
            return
        self.hash_ = v.refresh_hash
        d = json.loads(v.model_dump_json())
        for k in (
            "run_id",
            "recipe",
            "mode",
            "rounds",
            "fresh",
            "resumed_count",
            "process",
            "product",
            "elapsed",
            "remaining",
            "now_word",
            "now_text",
        ):
            setattr(self, k, d[k])
        self.last_halt = d.get("last_halt") or ""
        self.current_stage = d.get("current_stage") or ""
        self.stages = [_stage_of(s) for s in d["stages"]]
        self.gates = {s["id"]: _gate_of(s.get("gate")) for s in d["stages"] if s.get("gate")}
        self.chips = [
            ChipRow(key=c["key"], label=c["label"], count=c["count"], tone=c["tone"]) for c in d["chips"]
        ]
        self.agent_runs = [
            AgentRow(**{f.name: a[f.name] for f in dataclasses.fields(AgentRow)}) for a in d["agent_runs"]
        ]
        self.steps = [
            StepRow(
                **{f.name: x[f.name] for f in dataclasses.fields(StepRow) if f.name in x},
                label=T.k(x["tokens"]),
            )
            for x in d.get("steps", [])
        ]
        tl = d.get("timeline", [])
        span = max([r["end"] for r in tl] + [1.0])
        self.tl_total = _fmt_secs(span)
        self.timeline = [
            TLRow(
                step=r["step"],
                kind=r["kind"],
                lane=r["lane"],
                color=T.ACTOR.get(r["lane"], T.ACTOR["code"]),
                left=round(100 * r["start"] / span, 2),
                width=max(0.4, round(100 * (r["end"] - r["start"]) / span, 2)),
                call_left=round(100 * (r["call_start"] or 0) / span, 2),
                call_width=max(0.4, round(100 * ((r["call_end"] or 0) - (r["call_start"] or 0)) / span, 2)),
                has_call=r["call_start"] is not None,
                label=T.k(r["tokens"]) if r["tokens"] else "",
                seconds=_fmt_secs(r["end"] - r["start"]),
                done=bool(r["done"]),
            )
            for r in tl
        ]
        hues = {st["id"]: st["hue"] for st in d["stages"]}
        bands: list[TLBand] = []
        for sid in [st["id"] for st in d["stages"]]:
            mine = [r for r in tl if r.get("stage") == sid]
            if mine:
                lo, hi = min(r["start"] for r in mine), max(r["end"] for r in mine)
                bands.append(
                    TLBand(
                        stage=sid,
                        hue=hues.get(sid, "slate"),
                        left=round(100 * lo / span, 2),
                        width=max(0.2, round(100 * (hi - lo) / span, 2)),
                    )
                )
        self.tl_bands = bands
        self.tl_ticks = [
            TLTick(left=round(100 * f, 2), label=_fmt_secs(span * f)) for f in (0, 0.25, 0.5, 0.75, 1.0)
        ]
        self.events = [
            EventRow(**{f.name: e[f.name] for f in dataclasses.fields(EventRow)}) for e in d["events"]
        ]
        self.carried = [
            CarriedRow(
                id=str(c.get("id", "")), kind=str(c.get("kind", "")), summary=str(c.get("summary", ""))
            )
            for c in d["carried"]
        ]
        self.model_rows = [ModelRow(role=k, model=m) for k, m in d["models"].items()]
        self.token_rows = [
            TokenRow(role=k, n=n, label=T.k(n), cost=d.get("cost", {}).get(k, ""))
            for k, n in d["tokens"].items()
        ]
        self.cost_total = d.get("cost_total", "")
        self.cost_note = d.get("cost_note", "")
        self.artifacts = [ArtRow(**a) for a in d["artifacts"]]
        self.evals, self.evals_summary = _eval_rows(self.run_dir)
        self.runs = self._visible_runs()
        self.artifact_md = {k: render_artifact(self.run_dir, k) for k in self.open_paths}
        self.flagged = d["flagged"]
        self.report_md = d.get("report_md") or ""
        self.settings_rows = _settings_rows(self.run_dir)
        self.progress = float(d.get("progress", 0.0))
        self.stage_progress = [float(x) for x in d.get("stage_progress", [])]
        self.prog_rows = [
            ProgRow(hue=st["hue"], frac=float(f))
            for st, f in zip(d["stages"], self.stage_progress, strict=False)
        ]
        self.control, self.control_label, self.control_verb, self.control_tone = (
            d["control"],
            d["control_label"],
            d["control_verb"],
            d["control_tone"],
        )
        self.ring = d.get("dot_ring", "")
        if self.control == "done" and self.ring:
            self.control_tone = self.ring  # one colour for every indication of a finished run
        self.loaded = True

    @rx.event
    def load_providers(self):
        from code_steer_model_write.providers.status import all_statuses

        tone = {"configured": "ok", "missing_key": "warn", "not_on_path": "bad", "not_connected": "neutral"}
        self.providers = [
            ProviderRow(
                backend=x.backend,
                provider=x.provider,
                pill=x.pill,
                tone=tone[x.state],
                requirement=x.requirement,
                discovery=x.discovery,
                models=x.models,
            )
            for x in all_statuses()
        ]

    @rx.event
    def refresh_models(self):
        from code_steer_model_write.providers.status import refresh_catalogues

        refresh_catalogues()
        return S.load_providers

    @rx.event
    def load_runs(self):
        if self.view_tab not in {k for k, _ in NAV}:
            self.view_tab = "run"  # a stale pick from an earlier layout
        self.runs = self._visible_runs()
        if self.run_dir and self.run_dir not in {r["dir"] for r in self.runs}:
            self.run_dir = ""
        if not self.run_dir and self.runs:
            self.run_dir = self.runs[0]["dir"]
        self.hash_ = ""  # a page load rebuilds the view even when nothing on disk moved
        if self.run_dir:
            self._apply(self.run_dir)

    def _visible_runs(self) -> list[dict[str, str]]:
        """The one owner of the tab strip's list (ledger: a second owner of a fact -- the poll's
        refresh once rebuilt it without the hidden filter, so a closed tab came back a tick later)."""
        hidden = self._hidden()
        return [r for r in _runs() if r["dir"] not in hidden]

    def _hidden(self) -> set[str]:
        try:
            return set(json.loads(self.hidden_runs or "[]"))
        except ValueError:
            return set()

    @rx.event
    def close_run(self, run_dir: str):
        """The × on a tab: a live run is asked to stop (the STOP file, honoured at the next step
        boundary), then the tab is hidden in this browser. The run dir is never deleted."""
        if run_dir == self.run_dir and self.control in ("running", "gate"):
            atomic_write_text(Path(run_dir) / "STOP", "closed from the page")
        elif run_dir != self.run_dir:
            st = Path(run_dir) / "state.json"
            if st.exists() and json.loads(st.read_text()).get("status") == "RUNNING":
                atomic_write_text(Path(run_dir) / "STOP", "closed from the page")
        self.hidden_runs = json.dumps(sorted(self._hidden() | {run_dir}))
        self.load_runs()

    @rx.event
    def open_run(self, run_dir: str):
        self.run_dir = run_dir
        self.picked = ""
        self.hash_ = ""
        self._apply(run_dir)

    @rx.event(background=True)
    async def poll(self):
        while True:
            await asyncio.sleep(T.POLL_SECONDS)
            async with self:
                if self.run_dir:
                    self._apply(self.run_dir)

    # ---- picks (§7a rule 27: only a click sets a pick) ------------------------------------

    @rx.event
    def pick(self, stage_id: str):
        self.picked = stage_id

    @rx.event
    def jump_to_running(self):
        self.picked = ""

    @rx.event
    def toggle_detail(self):
        self.detail_full = not self.detail_full

    @rx.event
    def set_filter(self, phase: str):
        self.filter_phase = phase

    @rx.event
    def set_view(self, tab: str):
        self.view_tab = tab

    @rx.event
    def toggle_artifact(self, path: str):
        if path in self.open_paths:
            self.open_paths = [p for p in self.open_paths if p != path]
        else:
            self.open_paths = [*self.open_paths, path]
            self.artifact_md = {**self.artifact_md, path: render_artifact(self.run_dir, path)}

    @rx.var
    def stage_artifacts(self) -> list[ArtRow]:
        return [a for a in self.artifacts if a.stage == self.selected]

    @rx.var
    def selected(self) -> str:
        return self.picked or self.current_stage

    @rx.var
    def stage(self) -> Stage:
        for s in self.stages:
            if s.id == self.selected:
                return s
        return self.stages[0] if self.stages else Stage()

    @rx.var
    def stage_gate(self) -> GateView:
        return self.gates.get(self.selected, GateView())

    @rx.var
    def stage_has_gate(self) -> bool:
        return self.selected in self.gates

    @rx.var
    def stage_runs(self) -> list[AgentRow]:
        return [r for r in self.agent_runs if r.stage == self.selected]

    @rx.var
    def stage_steps(self) -> list[StepRow]:
        return [r for r in self.steps if r.stage == self.selected]

    @rx.var
    def stage_steps_done(self) -> str:
        rows = [r for r in self.steps if r.stage == self.selected]
        return f"{sum(1 for r in rows if r.status == 'done')}/{len(rows)} done"

    @rx.var
    def filtered_events(self) -> list[EventRow]:
        if self.filter_phase == "all":
            return self.events
        return [e for e in self.events if e.phase == self.filter_phase]

    @rx.var
    def is_running(self) -> bool:
        return self.process == "running"

    @rx.var
    def picked_elsewhere(self) -> bool:
        return (
            bool(self.picked)
            and self.picked != self.current_stage
            and self.control in ("running", "gate", "stopping")
        )

    @rx.var
    def stage_hue(self) -> str:
        return T.STAGE_HUES.get(self.stage.hue, T.MUTED)

    @rx.var
    def live_hue(self) -> str:
        """The running stage's hue: the only accent on the page."""
        cur = next((s for s in self.stages if s.id == self.current_stage), None)
        return T.STAGE_HUES.get(cur.hue, T.MUTED) if cur else T.MUTED

    @rx.var
    def percent(self) -> str:
        return f"{int(round(self.progress * 100))}%"

    @rx.var
    def gate_title(self) -> str:
        g = self.gates.get(self.current_stage)
        return g.title if g else ""

    @rx.var
    def has_open_gate(self) -> bool:
        return bool(self.gates)

    @rx.event
    def open_gate(self):
        self.picked = next(iter(self.gates), self.current_stage)
        self.view_tab = "run"

    @rx.var
    def status_word(self) -> str:
        """The run's state in a word, next to the progress: the one place it is spelled out."""
        return {
            "done": "Finished",
            "running": "Running",
            "stopping": "Stopping",
            "gate": "Waiting at a gate",
            "halted": "Halted",
            "stale": "Stale",
            "broke": "Broke",
            "queued": "Queued",
        }.get(self.control, self.control.capitalize())

    @rx.var
    def status_color(self) -> str:
        """The agreed tones (plan §7a.1): green running, amber gate, red halted or broke; a finished
        run green when clean and amber when items were carried, the same as its tab ring."""
        return {"ok": T.OK, "warn": T.WARN, "bad": T.BAD}.get(self.control_tone, T.DIM)

    @rx.var
    def now_color(self) -> str:
        return {"COMPLETE": T.OK, "HALT": T.BAD, "STALE": T.BAD, "GATE": T.WARN}.get(self.now_word, T.OK)

    # ---- the gate (one record; the form derives from it; the decision is a file) ------------

    @rx.event
    def set_answer(self, qid: str, value: str):
        self.answers = {**self.answers, qid: value}

    @rx.event
    def set_comment(self, row: str, value: str):
        self.comments = {**self.comments, row: value}

    @rx.event
    def decide(self, action: str):
        g = self.gates.get(self.selected)
        if g is None:
            return
        decisions = [
            Decision(
                question_id=q.id,
                answer=self.answers.get(q.id, q.recommended or q.default or ""),
                answered_by="human",
            )
            for q in g.questions
        ]
        d = GateDecision(
            gate=g.id,
            action=action,
            source="human",
            decisions=decisions,
            comments={k: v for k, v in self.comments.items() if v.strip()},
        )
        write_decision(RunPaths(run_dir=Path(self.run_dir)), d)
        self.answers = {}
        self.comments = {}
        self.hash_ = ""
        self._apply(self.run_dir)

    @rx.event
    def resume_run(self):
        """A stale or halted run continues from disk through the Gateway (L2): the same detached
        runner the CLI and the MCP server use, tracing on."""
        _gateway().resume(self.run_dir)

    @rx.event
    def run_again(self):
        """§7d piece 3: the task carried unchanged into a new run beside this one."""
        h = _gateway().run_again(self.run_dir)
        self.run_dir = h.run_dir
        self.picked = ""
        self.hash_ = ""
        self.load_runs()

    @rx.event
    def stop_run(self):
        atomic_write_text(Path(self.run_dir) / "STOP", "requested from the page")
        self.hash_ = ""
        self._apply(self.run_dir)

    @rx.event
    def control_click(self):
        """The one verb the run's state allows (docs/DASHBOARD-DESIGN.md, the control table)."""
        v = self.control_verb
        if v == "stop":
            return S.stop_run
        if v in ("resume", "start"):
            return S.resume_run
        if v == "answer":
            return S.open_gate
        if v == "report":
            self.view_tab = "evidence"
            self.detail_full = True
        return None


def _gateway():
    from code_steer_model_write.gateway.api import Gateway

    return Gateway()


def _fmt_secs(x: float) -> str:
    x = int(x)
    return (
        f"{x}s"
        if x < 60
        else (f"{x // 60}:{x % 60:02d}" if x < 3600 else f"{x // 3600}h{(x % 3600) // 60:02d}")
    )


# ---- styles --------------------------------------------------------------------------------

MONO = {"font_family": T.MONO}
SMALL = f"{T.SIZE['eyebrow']}px"
BODY = f"{T.SIZE['body']}px"
EYEBROW = {
    "font_family": T.MONO,
    "font_size": SMALL,
    "letter_spacing": T.LETTER_SPACING_EYEBROW,
    "text_transform": "uppercase",
    "color": T.MUTED,
}
CARD = {
    "background": T.CARD,
    "border": f"1px solid {T.BORDER}",
    "border_radius": T.RADIUS["card"],
    "padding": T.SPACE["lg"],
    "width": "100%",
}
SUBCARD = {
    "background": T.SUBCARD,
    "border": f"1px solid {T.BORDER}",
    "border_radius": T.RADIUS["box"],
    "padding": T.SPACE["md"],
}
HUE_MATCH = [(k, v) for k, v in T.STAGE_HUES.items()]
GLASS_FILL = [(k, T.tint(k, 0.10)) for k in T.STAGE_HUES]
GLASS_FILL_SEL = [(k, T.tint(k, 0.22)) for k in T.STAGE_HUES]
GLASS_STROKE = [(k, f"1px solid {T.tint(k, 0.55)}") for k in T.STAGE_HUES]
GLASS_STROKE_SEL = [(k, f"1.5px solid {T.tint(k, 0.95)}") for k in T.STAGE_HUES]


def eyebrow(text, right: rx.Component | None = None, *, color=None) -> rx.Component:
    """A card's title: uppercase mono, letter-spaced, muted (or the stage hue); a muted summary
    on its right. Every card on the page opens with one, so the eye reads them as one kind."""
    style = {**EYEBROW, "color": color} if color is not None else EYEBROW
    return rx.hstack(
        rx.text(text, **style), rx.spacer(), right or rx.fragment(), width="100%", align="center"
    )


def sub_eyebrow(text, right: rx.Component | None = None) -> rx.Component:
    """A section inside a card: the same face as the card title, one shade dimmer, spaced above."""
    return rx.hstack(
        rx.text(text, **{**EYEBROW, "color": T.DIM}),
        rx.spacer(),
        right or rx.fragment(),
        width="100%",
        align="center",
        margin_top=T.SPACE["md"],
    )


def summary_text(text) -> rx.Component:
    return rx.text(text, **MONO, color=T.MUTED, font_size=SMALL)


PILL_STYLE = {
    "font_family": T.MONO,
    "font_size": SMALL,
    "font_weight": "700",
    "letter_spacing": "0.08em",
    "text_transform": "uppercase",
}


def pill(text, tone="neutral", *, upper: bool = True) -> rx.Component:
    """The reference pill: a filled rounded rectangle with a faint tint of its colour, the text in
    that colour, bold, uppercase, letter-spaced. One component for status, chips and settings."""
    color = rx.match(
        tone,
        ("ok", T.PILL["ok"][0]),
        ("warn", T.PILL["warn"][0]),
        ("bad", T.PILL["bad"][0]),
        T.PILL["neutral"][0],
    )
    bg = rx.match(
        tone,
        ("ok", T.PILL["ok"][1]),
        ("warn", T.PILL["warn"][1]),
        ("bad", T.PILL["bad"][1]),
        T.PILL["neutral"][1],
    )
    style = dict(PILL_STYLE)
    if not upper:
        style.pop("text_transform")
    return rx.box(
        rx.text(text, **style, color=color),
        background=bg,
        border_radius="8px",
        padding="4px 11px",
        white_space="nowrap",
    )


def status_pill(text, tone) -> rx.Component:
    return pill(text, tone)


def setting_pill(label: str, value, actor: str = "") -> rx.Component:
    """A settings pill: the label uppercase, the value as it is (a model id keeps its case). The
    author's and the checker's pills carry their actor colour as glass; the rest stay neutral."""
    hue = T.ACTOR.get(actor)
    label_color = hue or T.PILL["neutral"][0]
    background = T.tint_hex(hue, 0.14) if hue else T.PILL["neutral"][1]
    return rx.box(
        rx.hstack(
            rx.text(label, **PILL_STYLE, color=label_color),
            rx.text(value, **MONO, font_size=SMALL, font_weight="700", color=T.TEXT),
            spacing="2",
            align="center",
        ),
        background=background,
        border_radius="8px",
        padding="4px 11px",
        white_space="nowrap",
    )


def chip(c: ChipRow) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(
                c.label, **PILL_STYLE, color=rx.match(c.tone, ("bad", T.PILL["bad"][0]), T.PILL["warn"][0])
            ),
            rx.text(
                c.count,
                **MONO,
                font_size=SMALL,
                font_weight="700",
                color=rx.match(c.tone, ("bad", T.PILL["bad"][0]), T.PILL["warn"][0]),
            ),
            spacing="2",
            align="center",
        ),
        background=rx.match(c.tone, ("bad", T.PILL["bad"][1]), T.PILL["warn"][1]),
        border_radius="8px",
        padding="4px 11px",
        white_space="nowrap",
    )


# ---- the rail: glass boxes (the only tinted surfaces) ------------------------------------------


def stage_box(s: Stage) -> rx.Component:
    hue = rx.match(s.hue, *HUE_MATCH, T.MUTED)
    selected = S.selected == s.id
    glyph = rx.match(s.state, ("done", "✓"), ("now", "●"), ("halted", "■"), "○")
    return rx.vstack(
        rx.hstack(
            rx.foreach(
                s.tokens,
                lambda t: rx.hstack(
                    side_mark(t.role == "author", "14px"),
                    rx.text(t.label, **MONO, color=T.MUTED, font_size=SMALL, white_space="nowrap"),
                    spacing="1",
                    align="center",
                ),
            ),
            width="100%",
            spacing="3",
            min_height="22px",
            align="center",
            justify="center",
        ),
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text(s.n, **MONO, color=hue, font_size=f"{T.SIZE['title']}px", font_weight="700"),
                    rx.text(
                        s.title,
                        font_weight="700",
                        font_size=f"{T.SIZE['title']}px",
                        color=hue,
                        white_space="nowrap",
                    ),
                    spacing="2",
                    align="center",
                    justify="center",
                ),
                rx.hstack(
                    rx.text(glyph, color=rx.cond(s.state == "halted", T.BAD, hue), font_size=SMALL),
                    rx.text(
                        rx.cond(s.rounds != "", f"{s.rounds} · {s.duration}", s.duration),
                        **MONO,
                        color=T.MUTED,
                        font_size=SMALL,
                    ),
                    spacing="2",
                    align="center",
                ),
                spacing="1",
                align="center",
            ),
            border=rx.cond(
                selected,
                rx.match(s.hue, *GLASS_STROKE_SEL, f"1.5px solid {T.BORDER_STRONG}"),
                rx.match(s.hue, *GLASS_STROKE, f"1px solid {T.BORDER}"),
            ),
            background=rx.cond(
                selected, rx.match(s.hue, *GLASS_FILL_SEL, T.CARD), rx.match(s.hue, *GLASS_FILL, T.CARD)
            ),
            opacity=rx.cond(s.state == "pending", "0.55", "1"),
            border_radius=T.RADIUS["box"],
            padding=T.SPACE["md"],
            width="100%",
            cursor="pointer",
            on_click=S.pick(s.id),
        ),
        rx.text(
            s.note,
            **MONO,
            color=T.MUTED,
            font_size=SMALL,
            text_align="center",
            width="100%",
            line_height="1.3",
            style={
                "display": "-webkit-box",
                "WebkitLineClamp": "2",
                "WebkitBoxOrient": "vertical",
                "overflow": "hidden",
            },
        ),
        spacing="1",
        width="100%",
        flex="1 1 0",
        min_width="0",
        overflow="hidden",
    )


def start_box() -> rx.Component:
    selected = S.selected == "start"
    return rx.vstack(
        rx.box(min_height="22px"),
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text("▸", color=T.STAGE_HUES["rose"], font_size=f"{T.SIZE['title']}px"),
                    rx.text(
                        "Start",
                        font_weight="700",
                        font_size=f"{T.SIZE['title']}px",
                        color=T.STAGE_HUES["rose"],
                    ),
                    spacing="2",
                    align="center",
                    justify="center",
                ),
                rx.text("Settings", **MONO, color=T.MUTED, font_size=SMALL),
                spacing="1",
                align="center",
            ),
            border=rx.cond(
                selected, f"1.5px solid {T.tint('rose', 0.95)}", f"1px solid {T.tint('rose', 0.55)}"
            ),
            background=rx.cond(selected, T.tint("rose", 0.22), T.tint("rose", 0.10)),
            border_radius=T.RADIUS["box"],
            padding=T.SPACE["md"],
            width="100%",
            cursor="pointer",
            on_click=S.pick("start"),
        ),
        rx.text(
            f"{S.mode} · rounds {S.rounds}",
            **MONO,
            color=T.MUTED,
            font_size=SMALL,
            text_align="center",
            width="100%",
            line_height="1.3",
            style={
                "display": "-webkit-box",
                "WebkitLineClamp": "2",
                "WebkitBoxOrient": "vertical",
                "overflow": "hidden",
            },
        ),
        spacing="1",
        width="100%",
        flex="0.8 1 0",
        min_width="0",
        overflow="hidden",
    )


def progress_segment(r: ProgRow) -> rx.Component:
    """One segment per stage in its hue, filled by that stage's fraction (the rail in miniature)."""
    hue = rx.match(r.hue, *HUE_MATCH, T.MUTED)
    return rx.box(
        rx.box(width=f"{r.frac * 100}%", height="100%", background=hue, border_radius="2px"),
        flex="1",
        height="8px",
        background=T.SUBCARD,
        border_radius="2px",
        overflow="hidden",
    )


BAR_WIDTH = "470px"  # as wide as the token line beneath it: two sides with cost, and the total


def progress_bar() -> rx.Component:
    """tqdm, with better graphics. A tight two-row column on the left: the segments per stage with
    the percentage and the elapsed time beside it, and beneath it the tokens and estimated cost
    per side centred under the bar. Beside it the wrong-ness chips in two rows. The run's state
    is the tab dot and the control button, not a word here."""
    tokens = rx.hstack(
        rx.foreach(
            S.token_rows,
            lambda t: rx.hstack(
                side_mark(t.role == "author", "13px"),
                rx.text(f"{t.label} tok", **MONO, font_weight="700", font_size=SMALL, white_space="nowrap"),
                rx.text(t.cost, **MONO, color=T.MUTED, font_size=SMALL, white_space="nowrap"),
                spacing="2",
                align="center",
            ),
        ),
        rx.text(f"TOT = {S.cost_total}", **MONO, font_weight="700", font_size=SMALL, white_space="nowrap"),
        rx.cond(
            S.cost_note != "",
            rx.text(
                S.cost_note,
                **MONO,
                color=T.DIM,
                font_size=SMALL,
                white_space="nowrap",
                title="a CLI on a subscription login is not billed per token; this is what the tokens would cost on the API",
            ),
            rx.fragment(),
        ),
        spacing="4",
        justify="center",
        align="center",
        width=BAR_WIDTH,
        white_space="nowrap",
    )
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.hstack(
                    rx.foreach(S.prog_rows, progress_segment), spacing="1", width=BAR_WIDTH, align="center"
                ),
                # the percentage and the elapsed time side by side on the bar's row, so the cost
                # line beneath has the whole width and nothing overlaps its "at API rates"
                rx.hstack(
                    rx.text(S.percent, **MONO, font_weight="700", font_size=BODY, white_space="nowrap"),
                    rx.text(
                        S.elapsed,
                        **MONO,
                        font_weight="700",
                        font_size=SMALL,
                        color=T.MUTED,
                        white_space="nowrap",
                    ),
                    spacing="2",
                    align="baseline",
                    flex_shrink="0",
                ),
                spacing="3",
                align="center",
            ),
            tokens,
            spacing="0",
            align="start",
        ),
        rx.grid(
            rx.foreach(S.chips, chip),
            grid_template_columns="auto auto",
            spacing="2",
            margin_left=T.SPACE["xl"],
            align_items="center",
            justify_items="start",
        ),
        spacing="3",
        justify="center",
        align="center",
        width="100%",
        margin_top=T.SPACE["lg"],
    )


def history_pill() -> rx.Component:
    """FRESH RUN in green, or RESUMED ×n in amber: whether the run has been picked up from disk."""
    return rx.box(
        rx.text(
            rx.cond(S.fresh, "FRESH RUN", f"RESUMED ×{S.resumed_count}"),
            **PILL_STYLE,
            color=rx.cond(S.fresh, T.PILL["ok"][0], T.PILL["warn"][0]),
        ),
        background=rx.cond(S.fresh, T.PILL["ok"][1], T.PILL["warn"][1]),
        border_radius="8px",
        padding="4px 11px",
        white_space="nowrap",
    )


def header() -> rx.Component:
    """One centred row of pills (the run's name, its history, the settings) with the Detail switch
    at the row's right; the rail; the progress row; the token line."""
    return rx.box(
        rx.box(
            rx.hstack(
                setting_pill("run", S.run_id),
                history_pill(),
                rx.foreach(
                    S.model_rows,
                    lambda m: rx.cond(
                        m.role == "author",
                        setting_pill("author", m.model, "a"),
                        setting_pill("checker", m.model, "b"),
                    ),
                ),
                setting_pill("rounds", S.rounds.to_string()),
                setting_pill("mode", S.mode),
                spacing="2",
                justify="center",
                align="center",
                width="100%",
                wrap="wrap",
                padding_right="120px",
            ),
            rx.box(
                rx.button(
                    rx.cond(S.detail_full, "Detail: Full", "Detail: Glance"),
                    on_click=S.toggle_detail,
                    size="1",
                    variant="soft",
                    color_scheme="gray",
                ),
                position="absolute",
                right="0",
                top="0",
            ),
            position="relative",
            width="100%",
        ),
        rx.hstack(
            start_box(),
            rx.foreach(S.stages, stage_box),
            spacing="3",
            width="100%",
            align="start",
            margin_top=T.SPACE["md"],
            overflow="hidden",
        ),
        progress_bar(),
        **CARD,
    )


# ---- panels (flat cards) ---------------------------------------------------------------------


def question_row(q: Question) -> rx.Component:
    return rx.vstack(
        rx.text(q.text, font_size=BODY),
        rx.hstack(
            rx.cond(
                q.kind == "confirm",
                rx.select(
                    ["yes", "no"],
                    default_value=rx.cond(q.default != "", q.default, "yes"),
                    on_change=lambda val: S.set_answer(q.id, val),
                    size="1",
                ),
                rx.input(
                    default_value=rx.cond(q.recommended != "", q.recommended, q.default),
                    on_change=lambda val: S.set_answer(q.id, val),
                    size="1",
                    width="180px",
                ),
            ),
            rx.input(
                placeholder="comment (your words, verbatim)",
                on_change=lambda val: S.set_comment(q.id, val),
                size="1",
                width="100%",
            ),
            width="100%",
        ),
        rx.cond(q.gloss != "", rx.text(q.gloss, color=T.MUTED, font_size=SMALL), rx.fragment()),
        spacing="1",
        width="100%",
        padding_bottom=T.SPACE["sm"],
        border_bottom=f"1px solid {T.BORDER}",
    )


def gate_form() -> rx.Component:
    g = S.stage_gate
    return rx.box(
        eyebrow(f"GATE — {g.title}", status_pill("WAITING FOR YOU", "warn")),
        rx.cond(
            g.carried.length() > 0,
            rx.vstack(
                rx.text("Carried, unresolved:", color=T.WARN, **MONO, font_size=SMALL),
                rx.foreach(g.carried, lambda c: rx.text(f"{c.id} · {c.argument}", font_size=BODY)),
                spacing="1",
                padding_bottom=T.SPACE["sm"],
            ),
            rx.fragment(),
        ),
        rx.vstack(rx.foreach(g.questions, question_row), spacing="2", width="100%"),
        rx.hstack(
            rx.button("Proceed", on_click=S.decide("proceed"), color_scheme="gray", variant="solid"),
            rx.cond(
                g.can_revise,
                rx.button(
                    "Send back with comments",
                    on_click=S.decide("revise"),
                    variant="soft",
                    color_scheme="gray",
                ),
                rx.fragment(),
            ),
            spacing="2",
            margin_top=T.SPACE["md"],
        ),
        **SUBCARD,
        width="100%",
        margin_top=T.SPACE["md"],
    )


def result_row(r: Row) -> rx.Component:
    color = rx.match(
        r.verdict,
        ("pass", T.OK),
        ("accepted", T.OK),
        ("fail", T.BAD),
        ("error", T.BAD),
        ("rejected", T.WARN),
        ("carried", T.WARN),
        T.MUTED,
    )
    return rx.hstack(
        rx.text(r.id, **MONO, color=T.MUTED, font_size=SMALL, min_width="64px"),
        rx.text(r.text, font_size=BODY),
        rx.spacer(),
        rx.text(f"{r.verdict} ({r.count})", **MONO, color=color, font_size=BODY),
        width="100%",
        align="center",
    )


def step_row(r: StepRow) -> rx.Component:
    """One step: its state glyph, its key, the side and model as pills, tokens and seconds when it
    ran. Done in text colour, running in the stage hue, pending dimmed: the eye follows the run."""
    color = rx.match(r.status, ("done", T.TEXT), ("running", S.stage_hue), T.DIM)
    glyph = rx.match(r.status, ("done", "✓"), ("running", "●"), "○")
    side = rx.match(
        r.role,
        ("author", setting_pill("author", r.model, "a")),
        ("checker", setting_pill("checker", r.model, "b")),
        ("you", setting_pill("you", "gate")),
        setting_pill("code", r.kind),
    )
    return rx.grid(
        rx.text(glyph, **MONO, color=color, font_size=BODY, text_align="center"),
        # the key column fits the longest key a recipe mints (contract_audit-arbitrate-r1);
        # a longer one clips with an ellipsis and shows whole on hover, never under the pill
        rx.text(
            r.step,
            **MONO,
            color=color,
            font_size=BODY,
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            title=r.step,
        ),
        rx.box(side, opacity=rx.cond(r.status == "pending", "0.55", "1")),
        rx.text(rx.cond(r.tokens > 0, f"{r.label} tok", ""), **MONO, color=T.MUTED, font_size=SMALL),
        rx.text(rx.cond(r.seconds > 0, f"{r.seconds}s", ""), **MONO, color=T.MUTED, font_size=SMALL),
        rx.text(r.status, **MONO, color=color, font_size=SMALL),
        # the side column is one fixed width, so tokens, seconds and status line up down the
        # list whatever pill a row carries (author, checker, you, code)
        grid_template_columns="18px 264px 216px 90px 70px 80px",
        column_gap="14px",
        align_items="center",
        width="100%",
    )


def stage_panel() -> rx.Component:
    s = S.stage
    return rx.box(
        eyebrow(f"STAGE {s.n} · {s.title}", summary_text(s.duration), color=S.stage_hue),
        rx.text(s.description, color=T.MUTED, font_size=BODY, margin_top=T.SPACE["xs"]),
        rx.cond(
            s.outcome != "",
            rx.text(
                s.outcome, font_weight="700", font_size=f"{T.SIZE['headline']}px", margin_top=T.SPACE["sm"]
            ),
            rx.fragment(),
        ),
        rx.cond(S.stage_has_gate, gate_form(), rx.fragment()),
        rx.cond(
            s.rows.length() > 0,
            rx.vstack(
                sub_eyebrow("RESULTS", summary_text(s.note)),
                rx.foreach(s.rows, result_row),
                spacing="1",
                width="100%",
            ),
            rx.fragment(),
        ),
        rx.vstack(
            sub_eyebrow("STEPS", summary_text(S.stage_steps_done)),
            rx.foreach(S.stage_steps, step_row),
            spacing="1",
            width="100%",
            id="stage-steps",
        ),
        border_top="2px solid " + S.stage_hue,
        **CARD,
    )


def artifact_row(a: ArtRow) -> rx.Component:
    is_open = S.open_paths.contains(a.path)
    return rx.vstack(
        rx.hstack(
            rx.text(
                rx.cond(is_open, "▾", "▸"),
                **MONO,
                color=T.TEXT,
                cursor="pointer",
                on_click=S.toggle_artifact(a.path),
                width="16px",
            ),
            rx.text(a.label, **MONO, font_size=BODY, cursor="pointer", on_click=S.toggle_artifact(a.path)),
            rx.text(a.kind, **MONO, color=T.DIM, font_size=SMALL),
            rx.spacer(),
            rx.text(a.path, **MONO, color=T.DIM, font_size=SMALL),
            width="100%",
            align="center",
        ),
        rx.cond(
            is_open,
            rx.box(
                rx.markdown(S.artifact_md[a.path]),
                **SUBCARD,
                margin_left="8px",
                width="100%",
                overflow_x="auto",
            ),
            rx.fragment(),
        ),
        spacing="1",
        width="100%",
    )


def artifacts_panel() -> rx.Component:
    return rx.box(
        eyebrow("OUTPUTS", summary_text(f"{S.stage_artifacts.length()} records · ▸ reads one as markdown")),
        rx.vstack(
            rx.foreach(S.stage_artifacts, artifact_row), spacing="2", width="100%", margin_top=T.SPACE["sm"]
        ),
        **CARD,
    )


TL_LABEL_W = "176px"
TL_TAIL_W = "116px"  # the seconds and the tokens after the track


def timeline_band(b: TLBand) -> rx.Component:
    """A stage's span as a glass band behind the rows, in the stage's hue (the rail's boxes)."""
    return rx.box(
        position="absolute",
        left=f"{b.left}%",
        width=f"{b.width}%",
        top="0",
        bottom="0",
        background=rx.match(b.hue, *GLASS_FILL, "transparent"),
        title=b.stage,
    )


def timeline_axis() -> rx.Component:
    """The time axis under the rows: ticks at the quarters of the run."""
    return rx.hstack(
        rx.box(width=TL_LABEL_W, min_width=TL_LABEL_W),
        rx.box(
            rx.foreach(
                S.tl_ticks,
                lambda t: rx.box(
                    rx.box(width="1px", height="5px", background=T.BORDER_STRONG),
                    rx.text(t.label, **MONO, color=T.DIM, font_size=SMALL, white_space="nowrap"),
                    position="absolute",
                    left=f"{t.left}%",
                    top="0",
                    transform="translateX(-50%)",
                    display="flex",
                    flex_direction="column",
                    align_items="center",
                ),
            ),
            position="relative",
            height="26px",
            width="100%",
            border_top=f"1px solid {T.BORDER_STRONG}",
        ),
        rx.box(width=TL_TAIL_W, min_width=TL_TAIL_W),
        width="100%",
        align="start",
        spacing="2",
        padding_top="2px",
    )


def timeline_row(r: TLRow) -> rx.Component:
    """§7d piece 2: the step's bar in its lane's colour, the model call a darker segment inside
    it, the key at the left and the tokens at the right. Overlapping rows are the parallel build."""
    color = r.color
    return rx.hstack(
        rx.text(
            r.step,
            **MONO,
            color=T.MUTED,
            font_size=SMALL,
            width=TL_LABEL_W,
            min_width=TL_LABEL_W,
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            title=f"{r.kind} · {r.seconds}",
        ),
        rx.box(
            rx.foreach(S.tl_bands, timeline_band),
            rx.box(
                position="absolute",
                left=f"{r.left}%",
                width=f"{r.width}%",
                height="10px",
                top="3px",
                background=color,
                opacity=rx.cond(r.done, "0.55", "0.35"),
                border_radius="2px",
            ),
            rx.cond(
                r.has_call,
                rx.box(
                    position="absolute",
                    left=f"{r.call_left}%",
                    width=f"{r.call_width}%",
                    height="10px",
                    top="3px",
                    background=color,
                    border_radius="2px",
                    title="the model call",
                ),
                rx.fragment(),
            ),
            position="relative",
            height="16px",
            width="100%",
            background=T.SUBCARD,
            border_radius="3px",
        ),
        rx.text(
            r.seconds,
            **MONO,
            color=T.DIM,
            font_size=SMALL,
            width="52px",
            min_width="52px",
            text_align="right",
        ),
        rx.text(
            r.label,
            **MONO,
            color=T.MUTED,
            font_size=SMALL,
            width="56px",
            min_width="56px",
            text_align="right",
        ),
        width="100%",
        align="center",
        spacing="2",
    )


def event_row(e: EventRow) -> rx.Component:
    return rx.hstack(
        rx.text(e.time, **MONO, color=T.DIM, min_width="44px"),
        rx.text(e.phase, **MONO, color=T.DIM, min_width="16px"),
        rx.text(e.kind, **MONO, color=T.MUTED, min_width="130px"),
        rx.text(e.text, **MONO),
        width="100%",
        font_size=SMALL,
    )


def evidence() -> rx.Component:
    return rx.box(
        eyebrow(
            "EVIDENCE",
            rx.text(
                f"timeline · {S.events.length()} events · run summary", **MONO, color=T.MUTED, font_size=SMALL
            ),
        ),
        rx.el.details(
            rx.el.summary(
                rx.text(
                    f"WHERE THE TIME WENT · {S.timeline.length()} steps · the whole run {S.elapsed}",
                    **{**EYEBROW, "color": T.DIM},
                    display="inline",
                )
            ),
            rx.vstack(
                rx.foreach(S.timeline, timeline_row),
                timeline_axis(),
                spacing="0",
                width="100%",
                padding_top="6px",
            ),
            id="run-timeline",
            open=True,
        ),
        rx.el.details(
            rx.el.summary(
                rx.text(f"CARRIED · {S.carried.length()}", **{**EYEBROW, "color": T.WARN}, display="inline")
            ),
            rx.foreach(S.carried, lambda c: rx.text(f"{c.kind} {c.id} · {c.summary}", font_size=BODY)),
            id="run-carried",
            open=S.detail_full,
        ),
        rx.el.details(
            rx.el.summary(
                rx.text(f"EVENT LOG · {S.events.length()}", **{**EYEBROW, "color": T.DIM}, display="inline")
            ),
            rx.hstack(
                rx.foreach(
                    ["all", "0", "1", "2", "3", "4"],
                    lambda p: rx.button(
                        p,
                        size="1",
                        color_scheme="gray",
                        variant=rx.cond(S.filter_phase == p, "solid", "soft"),
                        on_click=S.set_filter(p),
                    ),
                ),
                spacing="1",
            ),
            rx.vstack(
                rx.foreach(S.filtered_events, event_row),
                spacing="0",
                width="100%",
                max_height="480px",
                overflow_y="auto",
            ),
            id="run-event-log",
            open=S.detail_full,
        ),
        rx.el.details(
            rx.el.summary(rx.text("REPORT", **{**EYEBROW, "color": T.DIM}, display="inline")),
            rx.cond(S.report_md != "", rx.markdown(S.report_md), rx.text("not yet", color=T.DIM)),
            id="run-report",
            open=S.detail_full,
        ),
        **CARD,
    )


def setting_row(r: SettingRow) -> rx.Component:
    return rx.hstack(
        rx.text(r.name, **MONO, color=T.MUTED, font_size=SMALL, min_width="190px"),
        rx.text(r.value, **MONO, font_size=BODY),
        width="100%",
        align="start",
    )


def start_panel() -> rx.Component:
    return rx.box(
        eyebrow(
            "SETTINGS — WHAT THIS RUN WAS GIVEN",
            rx.link("New run like this ▸", href="/new", **MONO, font_size=SMALL, color=T.TEXT),
        ),
        rx.text(
            "The brief and every setting as chosen when the run started; a new run opens the form with the same picks.",
            color=T.MUTED,
            font_size=BODY,
        ),
        rx.vstack(
            rx.foreach(S.settings_rows, setting_row), spacing="1", width="100%", margin_top=T.SPACE["md"]
        ),
        **CARD,
    )


def provider_card(p: ProviderRow) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(p.backend, font_weight="700", font_size=BODY),
            rx.spacer(),
            status_pill(p.pill, p.tone),
            width="100%",
            align="center",
        ),
        rx.text(p.requirement, **MONO, color=T.MUTED, font_size=SMALL, margin_top=T.SPACE["xs"]),
        rx.text(f"{p.models} models · {p.discovery} discovery", **MONO, color=T.DIM, font_size=SMALL),
        rx.hstack(
            rx.button(
                "Refresh models", size="1", variant="soft", color_scheme="gray", on_click=S.refresh_models
            ),
            spacing="2",
            margin_top=T.SPACE["sm"],
        ),
        **SUBCARD,
        min_width="230px",
        flex="1 1 230px",
    )


def providers_panel() -> rx.Component:
    return rx.vstack(
        rx.box(
            rx.text("Providers", font_weight="700", font_size=f"{T.SIZE['headline']}px"),
            rx.text(
                "Each backend's readiness, from the same facts the doctor checks; a model catalogue is read from the CLI where it can say and from a maintained table where it cannot.",
                color=T.MUTED,
                font_size=BODY,
                margin_top=T.SPACE["xs"],
            ),
            rx.hstack(
                rx.foreach(S.providers, provider_card),
                spacing="3",
                wrap="wrap",
                width="100%",
                margin_top=T.SPACE["md"],
            ),
            **CARD,
        ),
        spacing="4",
        width="100%",
        on_mount=S.load_providers,
    )


# ---- the shell -------------------------------------------------------------------------------


def status_dot(dot, ring) -> rx.Component:
    """Green running, amber waiting, red halted; a finished run in the colour of its verdict, green
    clean or amber carried, the same colour the page uses everywhere for that run's state."""
    done_color = rx.match(ring, ("ok", T.OK), ("warn", T.WARN), T.DIM)
    color = rx.match(
        dot, ("running", T.OK), ("waiting", T.WARN), ("halted", T.BAD), ("done", done_color), T.DIM
    )
    return rx.box(width="9px", height="9px", border_radius="50%", background=color, flex_shrink="0")


def run_tab(r, *, active_allowed: bool = True) -> rx.Component:
    active = (S.run_dir == r["dir"]) if active_allowed else False
    return rx.hstack(
        status_dot(r["dot"], r["ring"]),
        rx.text(
            r["id"],
            **MONO,
            font_size=BODY,
            color=rx.cond(active, T.TEXT, T.MUTED),
            font_weight=rx.cond(active, "700", "400"),
            # a browser tab: the label clips before the row wraps
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            min_width="0",
        ),
        rx.text(r["recipe"], **MONO, font_size=SMALL, color=T.DIM, white_space="nowrap", flex_shrink="0"),
        rx.text(
            "×",
            **MONO,
            font_size=BODY,
            color=T.DIM,
            padding_left="6px",
            title="close: a live run is stopped first; the run dir stays",
            _hover={"color": T.TEXT},
            on_click=S.close_run(r["dir"]).stop_propagation,
        ),
        spacing="2",
        align="center",
        padding="8px 12px 8px 16px",
        cursor="pointer",
        on_click=S.open_run(r["dir"]),
        # like a browser's tabs: the strip is one row; a tab shrinks to a floor, never wraps
        flex="0 1 auto",
        min_width="96px",
        max_width="260px",
        overflow="hidden",
        title=r["id"],
        # browser tabs: a divider between neighbours, the open one lifted onto the card surface
        background=rx.cond(active, T.CARD, "transparent"),
        border_radius="8px 8px 0 0",
        border_right=f"1px solid {T.BORDER}",
        border_bottom=rx.cond(active, "2px solid " + S.live_hue, "2px solid transparent"),
    )


def runs_tabs(active: bool = True) -> rx.Component:
    return rx.hstack(
        rx.hstack(
            rx.foreach(S.runs, lambda r: run_tab(r, active_allowed=active)),
            spacing="0",
            align="end",
            # one row that scrolls sideways when the tabs outgrow it, never a second line
            flex="1 1 0",
            min_width="0",
            overflow_x="auto",
            overflow_y="hidden",
            flex_wrap="nowrap",
        ),
        rx.link(
            "New run ▸",
            href="/new",
            **MONO,
            font_size=SMALL,
            color=T.TEXT,
            padding="8px 14px",
            white_space="nowrap",
            flex_shrink="0",
        ),
        width="100%",
        border_bottom=f"1px solid {T.BORDER}",
        align="end",
        spacing="0",
        flex_wrap="nowrap",
    )


NAV = [
    ("run", "Run"),
    ("outputs", "Outputs"),
    ("evals", "Evals"),
    ("evidence", "Evidence"),
    ("settings", "Settings"),
    ("providers", "Providers"),
]
NAV_LINKS = [("runs", "Runs", "/"), ("new", "New run", "/new")]


def nav_row(key: str, label: str, *, active_key=None, href: str | None = None) -> rx.Component:
    active = (S.view_tab == key) if active_key is None else (active_key == key)
    row = rx.box(
        rx.text(
            label,
            font_size=BODY,
            font_weight=rx.cond(active, "700", "500"),
            color=rx.cond(active, T.TEXT, T.MUTED),
        ),
        padding="10px 14px",
        border_radius=T.RADIUS["box"],
        cursor="pointer",
        width="100%",
        background=rx.cond(active, T.SEL_FILL, "transparent"),
        border=rx.cond(active, f"1px solid {T.SEL_BORDER}", "1px solid transparent"),
        # a view row sets the view; when it is also a link (from another page, e.g. /new) it
        # does both, so the rail always moves the page (ledger: an effect with no owner --
        # the row changed a state nobody on that page rendered)
        on_click=S.set_view(key) if key in {k for k, _ in NAV} else None,
    )
    return rx.link(row, href=href, width="100%", underline="none") if href else row


def brand() -> rx.Component:
    return rx.hstack(
        rx.box(
            rx.image(src="/logo-64.png", width="30px", height="30px", alt="code steers, models write"),
            width="40px",
            height="40px",
            border_radius="10px",
            background=T.SUBCARD,
            border=f"1px solid {T.BORDER}",
            display="flex",
            align_items="center",
            justify_content="center",
        ),
        rx.vstack(
            rx.text("Code Steers", font_weight="700", font_size=BODY, line_height="1.15"),
            rx.text("Models Write", font_weight="700", font_size=BODY, line_height="1.15"),
            rx.text("Run control", color=T.MUTED, font_size=SMALL),
            spacing="0",
            align="start",
        ),
        spacing="3",
        align="center",
        padding="6px 4px 18px 4px",
    )


def sidebar(active: str | None = None) -> rx.Component:
    """The shell's left column: the brand, the views of a run, then the links (New run)."""
    # on the run page the view rows switch the view in place; on any other page they link home
    rows = [nav_row(k, v, active_key=active, href="/run") if active else nav_row(k, v) for k, v in NAV]
    rows += [nav_row(k, v, active_key=active or "", href=h) for k, v, h in NAV_LINKS]
    return rx.vstack(
        brand(),
        *rows,
        spacing="1",
        align="start",
        width=T.SIDEBAR_W,
        min_width=T.SIDEBAR_W,
        padding=T.SPACE["lg"],
        border_right=f"1px solid {T.BORDER}",
        min_height="100vh",
        background=T.SURFACE,
    )


def run_control_button() -> rx.Component:
    """The pill is the button: state word · verb, in the state's colour, disabled when no verb."""
    color = rx.match(
        S.control_tone,
        ("ok", T.PILL["ok"][0]),
        ("warn", T.PILL["warn"][0]),
        ("bad", T.PILL["bad"][0]),
        T.PILL["neutral"][0],
    )
    bg = rx.match(
        S.control_tone,
        ("ok", T.PILL["ok"][1]),
        ("warn", T.PILL["warn"][1]),
        ("bad", T.PILL["bad"][1]),
        T.PILL["neutral"][1],
    )
    return rx.box(
        rx.text(S.control_label, **PILL_STYLE, color=color),
        background=bg,
        border="1px solid transparent",
        border_radius="8px",
        padding="8px 14px",
        white_space="nowrap",
        cursor=rx.cond(S.control_verb != "", "pointer", "default"),
        opacity=rx.cond(S.control_verb != "", "1", "0.7"),
        on_click=S.control_click,
    )


def bottom_bar() -> rx.Component:
    """The next thing the run wants from you, and the one control that acts on it."""
    return rx.hstack(
        rx.box(width="3px", height="36px", background=S.status_color, border_radius="2px"),
        rx.text(S.now_text, font_weight="600", font_size=BODY),
        rx.spacer(),
        rx.cond(
            S.picked_elsewhere,
            rx.button(
                "jump to running", size="1", variant="soft", color_scheme="gray", on_click=S.jump_to_running
            ),
            rx.fragment(),
        ),
        rx.cond(
            S.control == "broke",
            rx.link("New run like this ▸", href="/new", **MONO, font_size=SMALL, color=T.TEXT),
            rx.fragment(),
        ),
        rx.cond(
            (S.control == "done") | (S.control == "halted") | (S.control == "stale") | (S.control == "broke"),
            rx.button(
                "run again",
                size="1",
                variant="soft",
                color_scheme="gray",
                title="the same task, a new run beside this one",
                on_click=S.run_again,
            ),
            rx.fragment(),
        ),
        run_control_button(),
        spacing="3",
        align="center",
        width="100%",
        padding=f"{T.SPACE['md']} {T.SPACE['lg']}",
        background=T.CARD,
        border_top=f"1px solid {T.BORDER}",
        position="sticky",
        bottom="0",
    )


def eval_row(r: EvalRow) -> rx.Component:
    color = rx.match(r.passed, ("pass", T.PILL["ok"][0]), ("fail", T.PILL["bad"][0]), T.MUTED)
    return rx.grid(
        rx.text(r.metric, **MONO, font_size=BODY, color=T.TEXT),
        rx.text(r.value, **MONO, font_size=BODY, font_weight="700", text_align="right"),
        rx.text(rx.cond(r.target != "", "target " + r.target, ""), **MONO, font_size=SMALL, color=T.MUTED),
        rx.text(r.passed, **MONO, font_size=SMALL, color=color, font_weight="700"),
        rx.text(r.tier, **MONO, font_size=SMALL, color=T.DIM),
        rx.text(r.note, font_size=SMALL, color=T.MUTED),
        grid_template_columns="180px 70px 110px 60px 60px 1fr",
        column_gap="14px",
        align_items="center",
        width="100%",
    )


def evals_panel() -> rx.Component:
    """L8's view (ARCHITECTURE.md 7.9): the recipe's eval specs scored over the record."""
    return rx.box(
        eyebrow("EVALS", summary_text(S.evals_summary)),
        rx.cond(
            S.evals.length() > 0,
            rx.vstack(rx.foreach(S.evals, eval_row), spacing="1", width="100%", margin_top=T.SPACE["sm"]),
            rx.text(
                "scored when the run completes", color=T.MUTED, font_size=SMALL, margin_top=T.SPACE["sm"]
            ),
        ),
        **CARD,
    )


def body() -> rx.Component:
    return rx.cond(
        S.selected == "start",
        start_panel(),
        rx.match(
            S.view_tab,
            ("outputs", artifacts_panel()),
            ("evals", evals_panel()),
            ("evidence", evidence()),
            ("settings", start_panel()),
            ("providers", providers_panel()),
            rx.vstack(stage_panel(), artifacts_panel(), evidence(), spacing="4", width="100%"),
        ),
    )


def index() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.vstack(
            rx.box(
                rx.vstack(
                    runs_tabs(),
                    rx.cond(
                        S.loaded,
                        rx.vstack(header(), body(), spacing="4", width="100%"),
                        rx.text("Pick a run.", color=T.MUTED),
                    ),
                    spacing="4",
                    width="100%",
                    padding=T.SPACE["lg"],
                ),
                flex="1",
                width="100%",
                overflow_y="auto",
            ),
            rx.cond(S.loaded, bottom_bar(), rx.fragment()),
            spacing="0",
            width="100%",
            min_height="100vh",
            flex="1",
        ),
        spacing="0",
        align="start",
        width="100%",
        background=T.SURFACE,
        color=T.TEXT,
        font_family=T.SANS,
        font_size=BODY,
        on_mount=[S.load_runs, S.poll],
    )


# ---- the home: every run (§7d piece 1), the trends (piece 4) --------------------------------


@dataclasses.dataclass
class HomeRowV:
    id: str = ""
    recipe: str = ""
    bucket: str = ""
    verdict: str = ""  # compact: "6/6 pass · 6/6 null-fail", or the halt's step and reason
    verdict_full: str = ""
    steps: str = ""
    elapsed: str = ""
    tokens: str = ""
    cost: str = ""
    started: str = ""
    dir: str = ""
    dot: str = "queued"
    ring: str = ""
    pass_rate: str = ""
    null_fail_rate: str = ""
    carried_findings: str = ""
    rounds_to_converge: str = ""
    refused_answers: str = ""
    can_stop: bool = False
    can_resume: bool = False
    is_done: bool = False


HOME_COLUMNS = [  # key, label, width, align, what the column means (the header's tooltip)
    ("id", "run", "168px", "start", "the run and its workflow; click the row to open it"),
    (
        "status",
        "status",
        "104px",
        "start",
        "running, completed, halted (resumable), failed, or stale (the record says running, the runner is gone)",
    ),
    (
        "verdict",
        "verdict",
        "minmax(180px, 1fr)",
        "start",
        "properties passing on the source, and failing on the null implementation; a halted run shows its halt",
    ),
    ("steps", "steps", "52px", "center", "steps done of the steps issued so far"),
    ("elapsed", "time", "52px", "center", "wall clock, start to end"),
    ("tokens", "tokens", "56px", "center", "tokens spent, input and output, every side"),
    ("cost", "cost", "56px", "center", "the tokens at API rates; a CLI login is billed flat"),
    ("pass_rate", "pass", "44px", "center", "eval: properties passing on the source, 0 to 1"),
    (
        "null_fail_rate",
        "null",
        "44px",
        "center",
        "eval: properties failing on the null implementation, 0 to 1 (a test that passes the null proves nothing)",
    ),
    ("carried_findings", "carried", "62px", "center", "eval: findings carried into the report unfixed"),
    (
        "rounds_to_converge",
        "rounds",
        "58px",
        "center",
        "eval: review rounds to converge, mean over the loops",
    ),
    ("refused_answers", "refused", "62px", "center", "eval: answers refused by a check and re-asked"),
    ("started", "started", "98px", "start", "when the run started"),
]
HOME_GRID = "28px " + " ".join(w for _, _, w, _, _ in HOME_COLUMNS) + " 116px"
HOME_MIN_W = "1160px"  # below this the card scrolls sideways, like a browser's table; nothing wraps


class H(rx.State):
    """The home's state: the rows from the registry (the one owner), the filters, the sort, the
    counters and the trends, every one a pure function in `dashboard/home.py`."""

    rows: list[HomeRowV] = []
    total: int = 0
    n_running: int = 0
    n_completed: int = 0
    n_halted: int = 0
    n_failed: int = 0
    status: str = "all"
    recipe: str = "all"
    recipes: list[str] = []
    query: str = ""
    sort_key: str = "started"
    sort_desc: bool = True
    trend: list[dict[str, Any]] = []
    trend_recipe: str = ""
    note: str = ""
    selected: list[str] = []  # run dirs ticked for a bulk remove
    confirm_remove: bool = False  # the button asks once before the list forgets them

    @rx.var
    def all_selected(self) -> bool:
        return bool(self.rows) and all(r.dir in self.selected for r in self.rows)

    @rx.event
    def toggle_select(self, run_dir: str, checked: bool):
        sel = set(self.selected)
        (sel.add if checked else sel.discard)(run_dir)
        self.selected = sorted(sel)
        self.confirm_remove = False

    @rx.event
    def select_all(self, checked: bool):
        self.selected = sorted(r.dir for r in self.rows) if checked else []
        self.confirm_remove = False

    @rx.event
    def remove_selected(self):
        """Two clicks: the first asks, the second forgets every ticked run. The folders stay."""
        if not self.confirm_remove:
            self.confirm_remove = True
            return
        gw = _gateway()
        n = 0
        for d in self.selected:
            try:
                gw.forget(d)
                n += 1
            except Exception as e:  # noqa: BLE001
                self.note = f"remove: {type(e).__name__}: {e}"
        self.selected, self.confirm_remove = [], False
        self.note = f"{n} run{'s' if n != 1 else ''} removed from the list; every folder stays on disk"
        self._reload()

    def _reload(self) -> None:
        all_rows = home.rows(_registry())
        c = home.counters(all_rows)
        self.total, self.n_running, self.n_completed = c["all"], c["running"], c["completed"]
        self.n_halted, self.n_failed = c["halted"] + c["stale"], c["failed"]
        self.recipes = home.recipes(all_rows)
        shown = home.sorted_rows(
            home.filtered(all_rows, status=self.status, recipe=self.recipe, query=self.query),
            self.sort_key,
            self.sort_desc,
        )
        self.rows = [
            HomeRowV(
                id=r.id,
                recipe=r.recipe,
                bucket=r.bucket,
                verdict=_short_verdict(r.verdict or (r.halt if r.bucket in ("halted", "failed") else "")),
                verdict_full=r.verdict or (r.halt if r.bucket in ("halted", "failed") else ""),
                steps=r.steps,
                elapsed=r.elapsed,
                tokens=r.tokens_label,
                cost=r.cost,
                started=r.started,
                dir=r.dir,
                dot=r.dot,
                ring=r.ring,
                pass_rate=r.evals.get("pass_rate", ""),
                null_fail_rate=r.evals.get("null_fail_rate", ""),
                carried_findings=r.evals.get("carried_findings", ""),
                rounds_to_converge=r.evals.get("rounds_to_converge", ""),
                refused_answers=r.evals.get("refused_answers", ""),
                can_stop=r.bucket == "running",
                can_resume=r.bucket in ("halted", "stale"),
                is_done=r.bucket in ("completed", "failed", "halted", "stale"),
            )
            for r in shown
        ]
        tr = self.recipe if self.recipe != "all" else (self.recipes[0] if self.recipes else "")
        if self.recipes and tr not in self.recipes:
            tr = self.recipes[0]
        self.trend_recipe = tr
        self.trend = home.trends(all_rows, tr) if tr else []

    @rx.event
    def load(self):
        self._reload()

    @rx.event(background=True)
    async def poll(self):
        while True:
            await asyncio.sleep(T.POLL_SECONDS)
            async with self:
                self._reload()

    @rx.event
    def set_status(self, v: str):
        self.status = v
        self._reload()

    @rx.event
    def set_recipe(self, v: str):
        self.recipe = v
        self._reload()

    @rx.event
    def set_query(self, v: str):
        self.query = v
        self._reload()

    @rx.event
    def sort_by(self, key: str):
        if key == self.sort_key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key in ("started", "tokens", "elapsed", "cost")
        self._reload()

    @rx.event
    async def open(self, run_dir: str):
        """A row opens its run. A tab closed earlier is hidden in this browser (ledger: a second
        owner) -- the home's click un-hides it, so the run page shows the run that was clicked."""
        s = await self.get_state(S)
        s.run_dir, s.picked, s.hash_ = run_dir, "", ""
        hidden = s._hidden()
        if run_dir in hidden:
            s.hidden_runs = json.dumps(sorted(hidden - {run_dir}))
        return rx.redirect("/run")

    def _act(self, verb: str, run_dir: str) -> None:
        gw = _gateway()
        try:
            if verb == "stop":
                gw.cancel(run_dir)
            elif verb == "pause":
                gw.pause(run_dir)
            elif verb == "resume":
                gw.resume(run_dir)
            elif verb == "again":
                h = gw.run_again(run_dir)
                self.note = f"started {h.run_id} on the {h.runner} runner" + (
                    f" ({gw.fallback_reason})" if gw.fallback_reason else ""
                )
            elif verb == "forget":
                gw.forget(run_dir)
        except Exception as e:  # noqa: BLE001 -- the reason is shown, never swallowed
            self.note = f"{verb}: {type(e).__name__}: {e}"
        self._reload()

    @rx.event
    def act(self, verb: str, run_dir: str):
        self._act(verb, run_dir)


def _short_verdict(v: str) -> str:
    """ "6/6 properties pass · 6/6 fail on the null" -> "6/6 pass · 6/6 null-fail"; a halt keeps
    its step and reason, the column's tooltip carries the whole text."""
    m = re.match(r"(\d+/\d+) properties pass · (\d+/\d+) fail on the null(.*)", v)
    if m:
        return f"{m.group(1)} pass · {m.group(2)} null-fail"
    return v


def home_counter(label: str, n, color) -> rx.Component:
    return rx.vstack(
        rx.text(n, **MONO, font_size="22px", font_weight="700", color=color, line_height="1"),
        rx.text(label, **EYEBROW),
        spacing="1",
        align="start",
        **SUBCARD,
        min_width="120px",
    )


def home_head_cell(key: str, label: str, align: str = "start", tip: str = "") -> rx.Component:
    active = H.sort_key == key
    return rx.text(
        rx.cond(active, rx.cond(H.sort_desc, f"{label} ▾", f"{label} ▴"), label),
        **{k: v for k, v in EYEBROW.items() if k not in ("color", "letter_spacing")},
        letter_spacing="0.02em",  # the table's headers are narrow columns; the eyebrow's spacing would clip them
        color=rx.cond(active, T.TEXT, T.MUTED),
        cursor="pointer",
        white_space="nowrap",
        overflow="hidden",
        text_overflow="ellipsis",
        text_align=align,
        title=tip,
        on_click=H.sort_by(key),
    )


def home_action(label: str, verb: str, r, *, show) -> rx.Component:
    return rx.cond(
        show,
        rx.text(
            label,
            **MONO,
            font_size=SMALL,
            color=T.MUTED,
            cursor="pointer",
            _hover={"color": T.TEXT},
            on_click=H.act(verb, r.dir).stop_propagation,
        ),
        rx.fragment(),
    )


def home_row(r: HomeRowV) -> rx.Component:
    def cell(v, align: str = "start", **kw) -> rx.Component:
        style = {"font_size": SMALL, "color": T.MUTED, **kw}
        return rx.text(
            v,
            **MONO,
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            text_align=align,
            **style,
        )

    tone = rx.match(
        r.bucket,
        ("running", "ok"),
        ("completed", "ok"),
        ("halted", "warn"),
        ("stale", "warn"),
        ("failed", "bad"),
        "neutral",
    )
    return rx.grid(
        rx.box(
            rx.checkbox(
                checked=H.selected.contains(r.dir),
                on_change=H.toggle_select(r.dir),
                size="1",
                color_scheme="gray",
            ),
            on_click=rx.stop_propagation,
        ),
        rx.hstack(
            status_dot(r.dot, r.ring),
            cell(r.id, color=T.TEXT, font_size=BODY, flex_shrink="0"),
            cell(r.recipe, color=T.DIM, min_width="0"),
            spacing="2",
            align="center",
            min_width="0",
        ),
        rx.box(  # the pill fits its column: a fixed width, the word clipped before it overflows
            rx.text(
                r.bucket,
                **{k: v for k, v in PILL_STYLE.items() if k != "font_size"},
                font_size="10px",
                color=rx.match(
                    tone,
                    ("ok", T.PILL["ok"][0]),
                    ("warn", T.PILL["warn"][0]),
                    ("bad", T.PILL["bad"][0]),
                    T.PILL["neutral"][0],
                ),
                overflow="hidden",
                text_overflow="ellipsis",
                text_align="center",
            ),
            background=rx.match(
                tone,
                ("ok", T.PILL["ok"][1]),
                ("warn", T.PILL["warn"][1]),
                ("bad", T.PILL["bad"][1]),
                T.PILL["neutral"][1],
            ),
            border_radius="8px",
            padding="4px 6px",
            width="96px",
            overflow="hidden",
        ),
        cell(r.verdict, title=r.verdict_full),
        cell(r.steps, "center"),
        cell(r.elapsed, "center"),
        cell(r.tokens, "center"),
        cell(r.cost, "center"),
        cell(r.pass_rate, "center"),
        cell(r.null_fail_rate, "center"),
        cell(r.carried_findings, "center"),
        cell(r.rounds_to_converge, "center"),
        cell(r.refused_answers, "center"),
        cell(r.started, color=T.DIM),
        rx.hstack(
            home_action("stop", "stop", r, show=r.can_stop),
            home_action("pause", "pause", r, show=r.can_stop),
            home_action("resume", "resume", r, show=r.can_resume),
            home_action("again", "again", r, show=r.is_done),
            spacing="3",
            justify="end",
            width="100%",
        ),
        grid_template_columns=HOME_GRID,
        align_items="center",
        gap="10px",
        width="100%",
        min_width=HOME_MIN_W,
        padding="8px 10px",
        border_bottom=f"1px solid {T.BORDER}",
        cursor="pointer",
        _hover={"background": T.SUBCARD},
        on_click=H.open(r.dir),
    )


def home_filter_chip(label: str, value: str, current, on_click) -> rx.Component:
    return rx.button(
        label,
        size="1",
        color_scheme="gray",
        variant=rx.cond(current == value, "solid", "soft"),
        on_click=on_click,
    )


def trend_chart(metric: str, label: str, color: str) -> rx.Component:
    return rx.vstack(
        rx.text(label, **EYEBROW),
        rx.recharts.line_chart(
            rx.recharts.line(
                data_key=metric, stroke=color, dot=False, stroke_width=2, is_animation_active=False
            ),
            rx.recharts.y_axis(hide=True),
            rx.recharts.x_axis(data_key="run", hide=True),
            rx.recharts.tooltip(),
            data=H.trend,
            height=70,
            width="100%",
            margin={"top": 4, "right": 4, "bottom": 0, "left": 4},
        ),
        spacing="1",
        align="start",
        **SUBCARD,
        flex="1",
        min_width="0",
    )


def home_page() -> rx.Component:
    return rx.hstack(
        sidebar(active="runs"),
        rx.box(
            rx.vstack(
                rx.hstack(
                    home_counter("running", H.n_running, T.OK),
                    home_counter("completed", H.n_completed, T.TEXT),
                    home_counter("halted", H.n_halted, T.WARN),
                    home_counter("failed", H.n_failed, T.BAD),
                    rx.spacer(),
                    rx.link(
                        rx.button("New run ▸", size="2", variant="soft", color_scheme="gray"), href="/new"
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                ),
                rx.cond(
                    H.trend.length() > 1,
                    rx.box(
                        eyebrow(
                            "TRENDS",
                            rx.text(f"{H.trend_recipe} · last {H.trend.length()} runs with evals", **EYEBROW),
                        ),
                        rx.hstack(
                            trend_chart("pass_rate", "pass rate", T.OK),
                            trend_chart("null_fail_rate", "null-fail rate", T.ACTOR["b"]),
                            trend_chart("carried_findings", "carried", T.WARN),
                            trend_chart("rounds_to_converge", "rounds", T.ACTOR["a"]),
                            trend_chart("refused_answers", "refused", T.BAD),
                            spacing="3",
                            width="100%",
                        ),
                        **CARD,
                    ),
                    rx.fragment(),
                ),
                rx.box(
                    eyebrow(
                        "RUNS",
                        rx.hstack(
                            rx.input(
                                placeholder="search",
                                value=H.query,
                                on_change=H.set_query,
                                size="1",
                                width="180px",
                            ),
                            rx.foreach(
                                ["all", "running", "completed", "halted", "failed"],
                                lambda v: home_filter_chip(v, v, H.status, H.set_status(v)),
                            ),
                            rx.cond(
                                H.recipes.length() > 1,
                                rx.hstack(
                                    home_filter_chip("every workflow", "all", H.recipe, H.set_recipe("all")),
                                    rx.foreach(
                                        H.recipes, lambda v: home_filter_chip(v, v, H.recipe, H.set_recipe(v))
                                    ),
                                    spacing="1",
                                ),
                                rx.fragment(),
                            ),
                            spacing="1",
                            align="center",
                        ),
                    ),
                    rx.grid(
                        rx.checkbox(
                            checked=H.all_selected,
                            on_change=H.select_all,
                            size="1",
                            color_scheme="gray",
                            title="select every run shown",
                        ),
                        *[home_head_cell(k, lbl, al, tip) for k, lbl, _, al, tip in HOME_COLUMNS],
                        rx.hstack(
                            rx.cond(
                                H.selected.length() > 0,
                                rx.button(
                                    rx.cond(
                                        H.confirm_remove,
                                        f"remove {H.selected.length()} from the list?",
                                        f"remove {H.selected.length()}",
                                    ),
                                    size="1",
                                    variant=rx.cond(H.confirm_remove, "solid", "soft"),
                                    color_scheme=rx.cond(H.confirm_remove, "red", "gray"),
                                    title="the list forgets them; every folder stays on disk",
                                    on_click=H.remove_selected,
                                ),
                                rx.fragment(),
                            ),
                            justify="end",
                            width="100%",
                        ),
                        grid_template_columns=HOME_GRID,
                        gap="10px",
                        width="100%",
                        min_width=HOME_MIN_W,
                        padding="6px 10px",
                        border_bottom=f"1px solid {T.BORDER_STRONG}",
                    ),
                    rx.cond(
                        H.rows.length() > 0,
                        rx.vstack(rx.foreach(H.rows, home_row), spacing="0", width="100%"),
                        rx.text("No runs match.", color=T.DIM, padding="12px 10px"),
                    ),
                    rx.text(
                        rx.cond(
                            H.note != "", H.note, f"{H.rows.length()} of {H.total} runs · costs at API rates"
                        ),
                        **MONO,
                        color=T.DIM,
                        font_size=SMALL,
                        padding_top="8px",
                    ),
                    **CARD,
                    overflow_x="auto",
                ),
                spacing="4",
                width="100%",
                padding=T.SPACE["lg"],
            ),
            flex="1",
            width="100%",
            overflow_y="auto",
            min_height="100vh",
        ),
        spacing="0",
        align="start",
        width="100%",
        background=T.SURFACE,
        color=T.TEXT,
        font_family=T.SANS,
        font_size=BODY,
        on_mount=[H.load, H.poll],
    )


app = rx.App(
    theme=rx.theme(appearance="dark", gray_color="slate"),
    # the browser-tab icon is the same PNG as the brand tile, so the two can never differ in colour;
    # the query string retires the icon a browser cached before the mark was recoloured
    head_components=[rx.el.link(rel="icon", type="image/png", href="/logo-64.png?v=3")],
)
app.add_page(home_page, route="/", title="csmw · runs")
app.add_page(index, route="/run", title="csmw")
app.add_page(start_page, route="/new", title="csmw · new run")
