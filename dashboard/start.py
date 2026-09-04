"""The start page (docs/PLAN.md §7c): the brief and the run's settings, one card per field of
`settings_form.FIELDS`, one row of chips per setting with the default's reason beside it, the
Start button that activates once the run name and the request are filled, a preview of the
stage rail, and one closing line. Starting a run writes the task, saves prefs.json, and spawns
`csmw run` detached; the page then follows it."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import reflex as rx

from code_steer_model_write import settings_form as sf
from code_steer_model_write.recipes import registry
from code_steer_model_write.state.lock import atomic_write_text
from code_steer_model_write.state.run import RunPaths, RunState

from . import theme as T

RUNS_DIR = Path(os.environ.get("CSMW_RUNS_DIR", "runs"))
MONO = {"font_family": T.MONO}
SMALL = f"{T.SIZE['eyebrow']}px"
BODY = f"{T.SIZE['body']}px"
CARD = {
    "background": T.CARD,
    "border": f"1px solid {T.BORDER}",
    "border_radius": T.RADIUS["card"],
    "padding": T.SPACE["lg"],
    "width": "100%",
}


@dataclasses.dataclass
class Card:
    key: str = ""
    name: str = ""
    description: str = ""
    kind: str = "chips"
    options: list[str] = dataclasses.field(default_factory=list)
    value: str = ""
    group: str = "settings"
    required: bool = False
    discovery: str = ""


@dataclasses.dataclass
class Tile:
    n: int = 0
    title: str = ""


class Start(rx.State):
    cards: list[Card] = []
    values: dict[str, str] = {}
    tiles: list[Tile] = []
    started: str = ""
    error: str = ""

    @rx.event
    def load(self):
        self.values = {**sf.defaults(), **sf.load_prefs(RUNS_DIR)}
        self.cards = [Card(**c) for c in sf.form_model(self.values)]
        self.tiles = [Tile(n=s.n, title=s.title) for s in registry.get("code_builder").spec.stages]

    @rx.event
    def set_value(self, key: str, value: str):
        self.values = {**self.values, key: value}
        self.cards = [Card(**c) for c in sf.form_model(self.values)]

    @rx.var
    def blocking(self) -> str:
        m = sf.missing_required(self.values)
        return (
            "The button activates once the "
            + " and the ".join(m)
            + (" are" if len(m) > 1 else " is")
            + " filled."
            if m
            else ""
        )

    @rx.var
    def ready(self) -> bool:
        return not sf.missing_required(self.values)

    @rx.event
    def start(self):
        if not self.ready:
            return
        task = sf.build_task(self.values)
        run_dir = RUNS_DIR / task.task_id
        if RunPaths(run_dir=run_dir).state.exists():
            self.error = f"a run already lives at {run_dir}; pick another run name"
            return
        sf.save_prefs(RUNS_DIR, self.values)
        RunState.create(RunPaths(run_dir=run_dir), task)
        atomic_write_text(run_dir / "task.json", task.model_dump_json(indent=2))
        subprocess.Popen(
            [sys.executable, "-m", "code_steer_model_write.cli", "resume", str(run_dir), "--no-mlflow"],
            stdout=(run_dir / "runner.log").open("w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(Path.cwd()),
        )
        self.started = task.task_id
        return rx.redirect("/")


def dropdown(card: Card) -> rx.Component:
    """One dropdown per setting (§7c): a model row lists the provider's catalogue for the chosen
    backend; an effort row lists the chosen model's efforts; the value is what is sent."""
    return rx.hstack(
        rx.select(
            card.options,
            value=card.value,
            on_change=lambda v: Start.set_value(card.key, v),
            size="2",
            width="280px",
        ),
        rx.cond(
            card.discovery != "", rx.text(card.discovery, **MONO, color=T.DIM, font_size=SMALL), rx.fragment()
        ),
        spacing="3",
        align="center",
    )


def card_view(card: Card) -> rx.Component:
    control = rx.match(
        card.kind,
        (
            "text",
            rx.input(
                default_value=card.value,
                placeholder=card.name,
                on_blur=lambda v: Start.set_value(card.key, v),
                width="420px",
                size="2",
            ),
        ),
        (
            "textarea",
            rx.text_area(
                default_value=card.value,
                placeholder=card.description,
                on_blur=lambda v: Start.set_value(card.key, v),
                width="100%",
                rows="3",
            ),
        ),
        (
            "lines",
            rx.text_area(
                default_value=card.value,
                placeholder=card.description,
                on_blur=lambda v: Start.set_value(card.key, v),
                width="100%",
                rows="3",
            ),
        ),
        dropdown(card),
    )
    return rx.hstack(
        rx.vstack(
            rx.text(card.name, font_weight="700", font_size=BODY),
            rx.text(card.description, color=T.MUTED, font_size=SMALL, line_height="1.35"),
            spacing="1",
            width="150px",
            min_width="150px",
            overflow="hidden",
            max_height="76px",
        ),
        rx.box(control, flex="1"),
        **CARD,
        align="start",
        spacing="4",
    )


def start_page() -> rx.Component:
    from .dashboard import sidebar

    return rx.hstack(
        sidebar(active="new"),
        rx.box(start_form(), flex="1", width="100%", overflow_y="auto", min_height="100vh"),
        spacing="0",
        align="start",
        width="100%",
        background=T.SURFACE,
        color=T.TEXT,
        font_family=T.SANS,
        on_mount=Start.load,
    )


def start_form() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("Run settings.", font_weight="700", font_size=BODY),
                rx.text(
                    "How much the run asks of you, and which models do the work.",
                    color=T.MUTED,
                    font_size=BODY,
                ),
                spacing="2",
            ),
            rx.foreach(Start.cards, card_view),
            rx.hstack(
                rx.button(
                    "Start the run ▸", on_click=Start.start, disabled=~Start.ready, color_scheme="blue"
                ),
                rx.text(Start.blocking, color=T.MUTED, font_size=SMALL),
                spacing="3",
                align="center",
            ),
            rx.cond(Start.error != "", rx.text(Start.error, color=T.BAD, font_size=SMALL), rx.fragment()),
            rx.hstack(
                rx.box(
                    rx.text("Start the run", font_weight="700"),
                    border=rx.cond(Start.ready, f"1px solid {T.LIVE}", f"1px dashed {T.BORDER_STRONG}"),
                    border_radius=T.RADIUS["box"],
                    padding="10px 14px",
                    cursor="pointer",
                    on_click=Start.start,
                ),
                rx.foreach(
                    Start.tiles,
                    lambda t: rx.box(
                        rx.text(t.n, **MONO, color=T.MUTED, font_size=SMALL),
                        rx.text(t.title.lower(), font_weight="700", font_size=BODY),
                        border=f"1px solid {T.BORDER}",
                        background=T.CARD,
                        border_radius=T.RADIUS["box"],
                        padding="8px 14px",
                        flex="1",
                    ),
                ),
                spacing="2",
                width="100%",
                position="sticky",
                bottom="0",
                background=T.SURFACE,
                padding_top=T.SPACE["sm"],
            ),
            rx.text(
                "This page follows the run and takes your choices directly. Times are local.",
                **MONO,
                font_style="italic",
                color=T.DIM,
                font_size=SMALL,
                text_align="center",
                width="100%",
            ),
            spacing="3",
            width="100%",
            max_width=T.PAGE_WIDTH,
            margin="0 auto",
            padding=T.SPACE["lg"],
        ),
        background=T.SURFACE,
        color=T.TEXT,
        min_height="100vh",
        font_family=T.SANS,
        on_mount=Start.load,
    )
