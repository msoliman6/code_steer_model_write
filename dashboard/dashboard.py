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
from pathlib import Path
from typing import Any

import reflex as rx

from code_steer_model_write.gates.gate import write_decision
from code_steer_model_write.spec.decisions import Decision, GateDecision
from code_steer_model_write.state.lock import atomic_write_text
from code_steer_model_write.state.run import RunPaths

from . import theme as T
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


def _run_dot(d: Path, st: dict[str, Any]) -> tuple[str, str]:
    """The tab's dot from the run's files: cheap, no events read. Green running, amber waiting
    for you, red halted or broke, grey done (ringed green when clean, amber when items carried)."""
    from code_steer_model_write.state.run import RunPaths, runner_alive

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


def _runs() -> list[dict[str, str]]:
    out = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if (d / "state.json").exists():
                st = json.loads((d / "state.json").read_text())
                dot, ring = _run_dot(d, st)
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


# ---- typed rows (Reflex iterates typed lists only) ----------------------------------------


@dataclasses.dataclass
class TokenRow:
    role: str = ""
    n: int = 0
    label: str = ""  # K / M


@dataclasses.dataclass
class ArtRow:
    stage: str = ""
    label: str = ""
    path: str = ""
    kind: str = ""


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
class Seg:
    lane: str = ""
    label: str = ""
    left: float = 0.0
    width: float = 0.0
    stage: str = ""
    kind: str = "call"


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
    segments: list[Seg] = []
    events: list[EventRow] = []
    carried: list[CarriedRow] = []
    model_rows: list[ModelRow] = []
    token_rows: list[TokenRow] = []
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
        total = max([sg["end"] for sg in d["segments"]] + [1.0])
        self.segments = [
            Seg(
                lane=sg["lane"],
                label=sg["label"],
                left=round(100 * sg["start"] / total, 2),
                width=max(0.6, round(100 * (sg["end"] - sg["start"]) / total, 2)),
                stage=sg["stage"],
                kind=sg["kind"],
            )
            for sg in d["segments"]
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
        self.token_rows = [TokenRow(role=k, n=n, label=T.k(n)) for k, n in d["tokens"].items()]
        self.artifacts = [ArtRow(**a) for a in d["artifacts"]]
        self.runs = _runs()
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
        self.runs = _runs()
        if not self.run_dir and self.runs:
            self.run_dir = self.runs[0]["dir"]
        self.hash_ = ""  # a page load rebuilds the view even when nothing on disk moved
        if self.run_dir:
            self._apply(self.run_dir)

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
    def filtered_events(self) -> list[EventRow]:
        if self.filter_phase == "all":
            return self.events
        return [e for e in self.events if e.phase == self.filter_phase]

    @rx.var
    def is_running(self) -> bool:
        return self.process == "running"

    @rx.var
    def picked_elsewhere(self) -> bool:
        return bool(self.picked) and self.picked != self.current_stage

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
        """A stale or halted run continues from disk in a detached `csmw resume`."""
        import subprocess
        import sys

        subprocess.Popen(
            [sys.executable, "-m", "code_steer_model_write.cli", "resume", self.run_dir, "--no-mlflow"],
            stdout=(Path(self.run_dir) / "runner.log").open("a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

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


def eyebrow(text, right: rx.Component | None = None) -> rx.Component:
    return rx.hstack(
        rx.text(text, **EYEBROW), rx.spacer(), right or rx.fragment(), width="100%", align="center"
    )


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


def setting_pill(label: str, value) -> rx.Component:
    """A settings pill: the label uppercase, the value as it is (a model id keeps its case)."""
    return rx.box(
        rx.hstack(
            rx.text(label, **PILL_STYLE, color=T.PILL["neutral"][0]),
            rx.text(value, **MONO, font_size=SMALL, font_weight="700", color=T.TEXT),
            spacing="2",
            align="center",
        ),
        background=T.PILL["neutral"][1],
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
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            width="100%",
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
                    rx.text("▸", color=T.MUTED, font_size=f"{T.SIZE['title']}px"),
                    rx.text("Start", font_weight="700", font_size=f"{T.SIZE['title']}px", color=T.TEXT),
                    spacing="2",
                    align="center",
                    justify="center",
                ),
                rx.text("settings", **MONO, color=T.MUTED, font_size=SMALL),
                spacing="1",
                align="center",
            ),
            border=rx.cond(
                selected, f"1.5px solid {T.tint('slate', 0.95)}", f"1px solid {T.tint('slate', 0.55)}"
            ),
            background=rx.cond(selected, T.tint("slate", 0.22), T.tint("slate", 0.10)),
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
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            width="100%",
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


def progress_bar() -> rx.Component:
    """tqdm, with better graphics: segments per stage, the percentage, elapsed, the estimate."""
    return rx.hstack(
        rx.hstack(
            rx.foreach(S.prog_rows, progress_segment),
            spacing="1",
            width="34%",
            align="center",
        ),
        rx.text(S.percent, **MONO, font_weight="700", font_size=BODY, min_width="44px"),
        rx.text(f"· {S.elapsed} elapsed", **MONO, color=T.MUTED, font_size=SMALL),
        rx.text(
            rx.cond(S.process == "completed", "· finished", "· remaining: steps (no history yet)"),
            **MONO,
            color=T.DIM,
            font_size=SMALL,
        ),
        spacing="3",
        align="center",
        width="100%",
        margin_top=T.SPACE["sm"],
    )


def header() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(S.run_id, **MONO, color=T.MUTED),
            rx.text("·", color=T.DIM),
            rx.text(S.recipe, **MONO, color=T.MUTED),
            rx.text("·", color=T.DIM),
            rx.text(S.mode, **MONO, color=T.MUTED),
            rx.text("·", color=T.DIM),
            rx.text(
                rx.cond(S.fresh, "Fresh run", f"Resumed ×{S.resumed_count}"),
                **MONO,
                color=rx.cond(S.fresh, T.OK, T.WARN),
            ),
            rx.spacer(),
            rx.button(
                rx.cond(S.detail_full, "Detail: Full", "Detail: Glance"),
                on_click=S.toggle_detail,
                size="1",
                variant="soft",
                color_scheme="gray",
            ),
            width="100%",
            align="center",
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
        rx.hstack(
            rx.foreach(S.model_rows, lambda m: setting_pill(m.role, m.model)),
            setting_pill("rounds", S.rounds.to_string()),
            setting_pill("mode", S.mode),
            spacing="2",
            margin_top=T.SPACE["md"],
            wrap="wrap",
        ),
        rx.hstack(
            rx.text("Elapsed", **MONO, color=T.MUTED),
            rx.text(S.elapsed, **MONO, font_weight="700", border_bottom="2px solid " + S.live_hue),
            rx.text(
                rx.cond(S.process == "completed", "Finished", f"Remaining {S.remaining}"),
                **MONO,
                color=T.MUTED,
            ),
            rx.foreach(
                S.token_rows,
                lambda t: rx.hstack(
                    rx.text(t.role, **MONO, color=T.MUTED),
                    rx.text(f"{t.label} tok", **MONO, font_weight="700"),
                    spacing="1",
                ),
            ),
            spacing="4",
            margin_top=T.SPACE["md"],
            align="center",
        ),
        rx.hstack(rx.foreach(S.chips, chip), spacing="2", margin_top=T.SPACE["sm"]),
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


def agent_row(r: AgentRow) -> rx.Component:
    return rx.hstack(
        rx.text(r.step, **MONO),
        rx.text(r.role, **MONO, color=T.MUTED),
        rx.text(r.model, **MONO, color=T.MUTED),
        rx.spacer(),
        rx.text(f"{r.tokens} tok · {r.seconds}s · {r.status}", **MONO, color=T.MUTED),
        width="100%",
        font_size=SMALL,
    )


def stage_panel() -> rx.Component:
    s = S.stage
    return rx.box(
        rx.text(f"Stage {s.n} · {s.title} · {s.author} + {s.checker}", **MONO, color=S.stage_hue),
        rx.text(s.description, color=T.MUTED, font_size=BODY, margin_top=T.SPACE["xs"]),
        rx.text(s.duration, **MONO, color=T.MUTED, font_size=SMALL, margin_top=T.SPACE["xs"]),
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
                eyebrow(f"RESULTS — {s.note}"),
                rx.foreach(s.rows, result_row),
                spacing="1",
                width="100%",
                margin_top=T.SPACE["md"],
            ),
            rx.fragment(),
        ),
        rx.el.details(
            rx.el.summary(
                rx.text(f"Agent runs · {S.stage_runs.length()}", **MONO, color=T.MUTED, font_size=BODY)
            ),
            rx.foreach(S.stage_runs, agent_row),
            id="stage-agent-runs",
            open=S.detail_full,
            margin_top=T.SPACE["md"],
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
        eyebrow(
            "OUTPUTS OF THIS STAGE",
            rx.text(
                f"{S.stage_artifacts.length()} records · ▸ reads one as markdown",
                **MONO,
                color=T.MUTED,
                font_size=SMALL,
            ),
        ),
        rx.vstack(
            rx.foreach(S.stage_artifacts, artifact_row), spacing="2", width="100%", margin_top=T.SPACE["sm"]
        ),
        **CARD,
    )


def lane_row(lane: str) -> rx.Component:
    color = {"a": T.ACTOR["a"], "b": T.ACTOR["b"], "you": T.ACTOR["you"]}[lane]
    return rx.hstack(
        rx.text(lane, **MONO, color=T.MUTED, min_width="40px", font_size=SMALL),
        rx.box(
            rx.foreach(
                S.segments,
                lambda sg: rx.cond(
                    sg.lane == lane,
                    rx.box(
                        position="absolute",
                        left=f"{sg.left}%",
                        width=rx.cond(sg.kind == "call", f"{sg.width}%", "8px"),
                        height="10px",
                        top="4px",
                        background=color,
                        border_radius="2px",
                        title=sg.label,
                    ),
                    rx.fragment(),
                ),
            ),
            position="relative",
            height="18px",
            width="100%",
            background=T.SUBCARD,
            border_radius="4px",
        ),
        width="100%",
        align="center",
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
                f"swimlane · {S.events.length()} events · run summary", **MONO, color=T.MUTED, font_size=SMALL
            ),
        ),
        rx.box(
            eyebrow("WHERE THE TIME WENT"),
            lane_row("a"),
            lane_row("b"),
            lane_row("you"),
            rx.text(f"The whole run · {S.elapsed}", **MONO, color=T.MUTED, font_size=SMALL),
            width="100%",
            padding_top=T.SPACE["sm"],
        ),
        rx.el.details(
            rx.el.summary(rx.text(f"Carried · {S.carried.length()}", **MONO, color=T.WARN, font_size=BODY)),
            rx.foreach(S.carried, lambda c: rx.text(f"{c.kind} {c.id} · {c.summary}", font_size=BODY)),
            id="run-carried",
            open=S.detail_full,
        ),
        rx.el.details(
            rx.el.summary(rx.text(f"Event log · {S.events.length()}", **MONO, color=T.MUTED, font_size=BODY)),
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
            rx.el.summary(rx.text("Report", **MONO, color=T.MUTED, font_size=BODY)),
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
    color = rx.match(dot, ("running", T.OK), ("waiting", T.WARN), ("halted", T.BAD), T.DIM)
    ring_css = rx.match(ring, ("ok", f"0 0 0 2px {T.OK}55"), ("warn", f"0 0 0 2px {T.WARN}66"), "none")
    return rx.box(
        width="9px", height="9px", border_radius="50%", background=color, box_shadow=ring_css, flex_shrink="0"
    )


def run_tab(r) -> rx.Component:
    active = S.run_dir == r["dir"]
    return rx.hstack(
        status_dot(r["dot"], r["ring"]),
        rx.text(
            r["id"],
            **MONO,
            font_size=BODY,
            color=rx.cond(active, T.TEXT, T.MUTED),
            font_weight=rx.cond(active, "700", "400"),
        ),
        rx.text(r["recipe"], **MONO, font_size=SMALL, color=T.DIM),
        spacing="2",
        align="center",
        padding="8px 14px",
        cursor="pointer",
        on_click=S.open_run(r["dir"]),
        border_bottom=rx.cond(active, "2px solid " + S.live_hue, "2px solid transparent"),
    )


def runs_tabs() -> rx.Component:
    return rx.hstack(
        rx.foreach(S.runs, run_tab),
        rx.spacer(),
        rx.link("New run ▸", href="/new", **MONO, font_size=SMALL, color=T.TEXT, padding="8px 14px"),
        width="100%",
        border_bottom=f"1px solid {T.BORDER}",
        align="end",
        spacing="0",
    )


NAV = [
    ("run", "Run"),
    ("outputs", "Outputs"),
    ("evidence", "Evidence"),
    ("settings", "Settings"),
    ("providers", "Providers"),
]
NAV_LINKS = [("new", "New run", "/new")]


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
        on_click=None if href else S.set_view(key),
    )
    return rx.link(row, href=href, width="100%", underline="none") if href else row


def brand() -> rx.Component:
    return rx.hstack(
        rx.box(
            rx.text("🧊", font_size="18px"),
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
    rows = [nav_row(k, v, active_key=active) if active else nav_row(k, v) for k, v in NAV]
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
        rx.box(width="3px", height="36px", background=S.live_hue, border_radius="2px"),
        rx.vstack(
            rx.hstack(
                rx.box(width="8px", height="8px", border_radius="50%", background=S.now_color),
                rx.text(
                    S.now_word,
                    **MONO,
                    font_size=SMALL,
                    color=T.MUTED,
                    letter_spacing=T.LETTER_SPACING_EYEBROW,
                ),
                spacing="2",
                align="center",
            ),
            rx.text(S.now_text, font_weight="600", font_size=BODY),
            spacing="0",
            align="start",
        ),
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


def body() -> rx.Component:
    return rx.cond(
        S.selected == "start",
        start_panel(),
        rx.match(
            S.view_tab,
            ("outputs", artifacts_panel()),
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


app = rx.App(theme=rx.theme(appearance="dark", gray_color="slate"))
app.add_page(index, route="/", title="csmw")
app.add_page(start_page, route="/new", title="csmw · new run")
