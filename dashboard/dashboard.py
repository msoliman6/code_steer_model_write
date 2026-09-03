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
from .model import build_view
from .start import start_page

RUNS_DIR = Path(os.environ.get("CSMW_RUNS_DIR", "runs"))


def _runs() -> list[dict[str, str]]:
    out = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if (d / "state.json").exists():
                st = json.loads((d / "state.json").read_text())
                out.append(
                    {"id": st["run_id"], "recipe": st["recipe"], "status": st["status"], "dir": str(d)}
                )
    return out


# ---- typed rows (Reflex iterates typed lists only) ----------------------------------------


@dataclasses.dataclass
class TokenRow:
    role: str = ""
    n: int = 0


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
        tokens=[TokenRow(role=k, n=v) for k, v in s.get("tokens", {}).items()],
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
        self.token_rows = [TokenRow(role=k, n=n) for k, n in d["tokens"].items()]
        self.flagged = d["flagged"]
        self.report_md = d.get("report_md") or ""
        self.loaded = True

    @rx.event
    def load_runs(self):
        self.runs = _runs()
        if not self.run_dir and self.runs:
            self.run_dir = self.runs[0]["dir"]
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
    def now_color(self) -> str:
        return {"COMPLETE": T.OK, "HALT": T.BAD, "GATE": T.WARN}.get(self.now_word, T.LIVE)

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
    def stop_run(self):
        atomic_write_text(Path(self.run_dir) / "STOP", "requested from the page")


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
HUE_MATCH = [(k, v) for k, v in T.STAGE_HUES.items()]


def eyebrow(text, right: rx.Component | None = None) -> rx.Component:
    return rx.hstack(
        rx.text(text, **EYEBROW), rx.spacer(), right or rx.fragment(), width="100%", align="center"
    )


def pill(text) -> rx.Component:
    return rx.box(
        rx.text(text, **MONO, font_size=SMALL, color=T.MUTED),
        border=f"1px solid {T.BORDER}",
        border_radius=T.RADIUS["chip"],
        padding="2px 10px",
    )


def chip(c: ChipRow) -> rx.Component:
    color = rx.match(c.tone, ("bad", T.BAD), ("live", T.LIVE), T.WARN)
    return rx.box(
        rx.hstack(
            rx.text(c.label, **MONO, font_size=SMALL),
            rx.text(c.count, **MONO, font_size=SMALL, font_weight="700"),
            spacing="2",
        ),
        border=f"1px solid {color}",
        color=color,
        border_radius=T.RADIUS["chip"],
        padding="2px 10px",
    )


def stage_box(s: Stage) -> rx.Component:
    hue = rx.match(s.hue, *HUE_MATCH, T.MUTED)
    selected = S.selected == s.id
    glyph = rx.match(s.state, ("done", "✓"), ("now", "●"), ("halted", "■"), "○")
    return rx.vstack(
        rx.hstack(
            rx.text(s.n, **MONO, color=hue, font_size=SMALL),
            rx.text("·", color=T.DIM),
            rx.text(s.author, **MONO, color=T.MUTED, font_size=SMALL),
            rx.spacer(),
            rx.foreach(
                s.tokens,
                lambda t: rx.text(f"{t.role} {t.n}", **MONO, color=T.MUTED, font_size=SMALL),
            ),
            width="100%",
        ),
        rx.box(
            rx.vstack(
                rx.text(glyph, color=rx.cond(s.state == "halted", T.BAD, hue)),
                rx.text(s.title, font_weight="700", font_size=f"{T.SIZE['title']}px", color=T.TEXT),
                rx.text(
                    rx.cond(s.rounds != "", f"{s.rounds} · {s.duration}", s.duration),
                    **MONO,
                    color=T.MUTED,
                    font_size=SMALL,
                ),
                spacing="1",
                align="center",
            ),
            border=rx.cond(selected, f"2px solid {T.BORDER_STRONG}", f"1px solid {T.BORDER}"),
            border_top=f"2px solid {hue}",
            opacity=rx.cond(s.state == "pending", "0.6", "1"),
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
            ),
            width="100%",
            align="center",
        ),
        rx.hstack(
            rx.foreach(S.stages, stage_box),
            spacing="3",
            width="100%",
            align="start",
            margin_top=T.SPACE["md"],
        ),
        rx.hstack(
            rx.foreach(S.model_rows, lambda m: pill(f"{m.role} {m.model}")),
            pill(f"Rounds {S.rounds}"),
            pill(S.mode),
            spacing="2",
            margin_top=T.SPACE["md"],
            wrap="wrap",
        ),
        rx.hstack(
            rx.text("Elapsed", **MONO, color=T.MUTED),
            rx.text(S.elapsed, **MONO, font_weight="700", border_bottom=f"2px solid {T.LIVE}"),
            rx.text(
                rx.cond(S.process == "completed", "Finished", f"Remaining {S.remaining}"),
                **MONO,
                color=T.MUTED,
            ),
            rx.foreach(
                S.token_rows,
                lambda t: rx.hstack(
                    rx.text(t.role, **MONO, color=T.MUTED),
                    rx.text(f"{t.n} tok", **MONO, font_weight="700"),
                    spacing="1",
                ),
            ),
            spacing="4",
            margin_top=T.SPACE["md"],
            align="center",
        ),
        rx.hstack(
            rx.box(width="8px", height="8px", border_radius="50%", background=S.now_color),
            rx.text(
                S.now_word, **MONO, font_size=SMALL, color=T.MUTED, letter_spacing=T.LETTER_SPACING_EYEBROW
            ),
            rx.text(S.now_text, font_weight="600"),
            rx.spacer(),
            rx.cond(
                S.picked_elsewhere,
                rx.button("jump to running", size="1", variant="soft", on_click=S.jump_to_running),
                rx.fragment(),
            ),
            rx.cond(
                S.is_running,
                rx.button("Stop", size="1", color_scheme="red", variant="soft", on_click=S.stop_run),
                rx.fragment(),
            ),
            background=T.SURFACE,
            border=f"1px solid {T.BORDER}",
            border_radius=T.RADIUS["box"],
            padding=T.SPACE["md"],
            width="100%",
            align="center",
            margin_top=T.SPACE["md"],
        ),
        rx.hstack(rx.foreach(S.chips, chip), spacing="2", margin_top=T.SPACE["sm"]),
        **CARD,
    )


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
        eyebrow(f"GATE — {g.title}", rx.text(g.kind, **MONO, color=T.MUTED, font_size=SMALL)),
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
            rx.button("Proceed", on_click=S.decide("proceed"), color_scheme="green"),
            rx.cond(
                g.can_revise,
                rx.button("Send back with comments", on_click=S.decide("revise"), variant="soft"),
                rx.fragment(),
            ),
            spacing="2",
            margin_top=T.SPACE["md"],
        ),
        border=f"1px solid {T.WARN}",
        border_radius=T.RADIUS["box"],
        padding=T.SPACE["md"],
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
        rx.text(
            r.tokens.to_string() + " tok · " + r.seconds.to_string() + "s · " + r.status,
            **MONO,
            color=T.MUTED,
        ),
        width="100%",
        font_size=SMALL,
    )


def stage_panel() -> rx.Component:
    s = S.stage
    return rx.box(
        rx.text(
            "Stage " + s.n.to_string() + " · " + s.title + " · " + s.author + " + " + s.checker,
            **MONO,
            color=S.stage_hue,
        ),
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
                rx.text(
                    "Agent runs · " + S.stage_runs.length().to_string(), **MONO, color=T.MUTED, font_size=BODY
                )
            ),
            rx.foreach(S.stage_runs, agent_row),
            id="stage-agent-runs",
            open=S.detail_full,
            margin_top=T.SPACE["md"],
        ),
        border_top=f"2px solid {S.stage_hue}",
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
            background=T.SURFACE,
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
                "swimlane · " + S.events.length().to_string() + " events · run summary",
                **MONO,
                color=T.MUTED,
                font_size=SMALL,
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


def runs_list() -> rx.Component:
    return rx.box(
        eyebrow("RUNS"),
        rx.foreach(
            S.runs,
            lambda r: rx.hstack(
                rx.button(
                    r["id"],
                    size="1",
                    variant=rx.cond(S.run_dir == r["dir"], "solid", "soft"),
                    on_click=S.open_run(r["dir"]),
                ),
                rx.text(r["recipe"], **MONO, color=T.MUTED),
                rx.text(r["status"], **MONO, color=T.MUTED),
                spacing="2",
            ),
        ),
        **CARD,
    )


def index() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("CODE STEERS · MODELS WRITE", **EYEBROW),
                rx.spacer(),
                rx.link("New run ▸", href="/new", **MONO, font_size=SMALL, color=T.LIVE),
                width="100%",
            ),
            rx.text(
                rx.cond(S.loaded, S.run_id, "no run"), font_size=f"{T.SIZE['page']}px", font_weight="700"
            ),
            runs_list(),
            rx.cond(
                S.loaded,
                rx.vstack(header(), stage_panel(), evidence(), spacing="4", width="100%"),
                rx.text("Pick a run.", color=T.MUTED),
            ),
            spacing="4",
            width="100%",
            max_width=T.PAGE_WIDTH,
            margin="0 auto",
            padding=T.SPACE["lg"],
        ),
        background=T.SURFACE,
        color=T.TEXT,
        min_height="100vh",
        font_family=T.SANS,
        font_size=BODY,
        on_mount=[S.load_runs, S.poll],
    )


app = rx.App(theme=rx.theme(appearance="dark"))
app.add_page(index, route="/", title="csmw")
app.add_page(start_page, route="/new", title="csmw · new run")
