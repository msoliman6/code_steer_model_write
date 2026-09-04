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
    side: str = ""
    func: str = ""
    field: str = ""


@dataclasses.dataclass
class Tile:
    n: int = 0
    id: str = ""
    title: str = ""
    emoji: str = ""
    hue: str = "slate"
    author: str = ""
    checker: str = ""


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
        self.tiles = [
            Tile(n=s.n, id=s.id, title=s.title, emoji=s.emoji, hue=s.hue, author=s.author, checker=s.checker)
            for s in registry.get("code_builder").spec.stages
        ]

    @rx.event
    def set_value(self, key: str, value: str):
        self.values = {**self.values, key: value}
        self.cards = [Card(**c) for c in sf.form_model(self.values)]

    @rx.var
    def universal_cards(self) -> list[Card]:
        return [c for c in self.cards if not c.group.startswith("stage:")]

    @rx.var
    def brief_cards(self) -> list[Card]:
        return [c for c in self.cards if c.group == "brief"]

    @rx.var
    def run_cards(self) -> list[Card]:
        return [c for c in self.cards if c.key in ("mode", "rounds")]

    @rx.var
    def author_cards(self) -> list[Card]:
        by = {c.key: c for c in self.cards}
        return [by[k] for k in ("author_backend", "author_model", "author_effort") if k in by]

    @rx.var
    def checker_cards(self) -> list[Card]:
        by = {c.key: c for c in self.cards}
        return [by[k] for k in ("checker_backend", "checker_model", "checker_effort") if k in by]

    @rx.var
    def stage_cards(self) -> dict[str, list[Card]]:
        out: dict[str, list[Card]] = {}
        for c in self.cards:
            if c.group.startswith("stage:"):
                out.setdefault(c.group.split(":", 1)[1], []).append(c)
        return out

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
        n = 2
        while RunPaths(run_dir=run_dir).state.exists():  # a second run of the same module: -2, -3, ...
            run_dir = RUNS_DIR / f"{task.task_id}-{n}"
            n += 1
        task = task.model_copy(update={"task_id": run_dir.name})
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


def centered_select(options, value, on_change, *, width: str = "100%") -> rx.Component:
    """A dropdown whose trigger and items are centred (the stage columns are symmetric)."""
    return rx.select.root(
        rx.select.trigger(width=width, style={"justify_content": "center", "text_align": "center"}),
        rx.select.content(
            rx.foreach(options, lambda o: rx.select.item(o, value=o, style={"justify_content": "center"}))
        ),
        value=value,
        on_change=on_change,
        size="2",
    )


def dropdown(card: Card, *, width: str = "280px") -> rx.Component:
    """One dropdown per setting (§7c), its text centred; a model row lists the provider's
    catalogue for the chosen backend, an effort row the chosen model's efforts."""
    return rx.hstack(
        centered_select(card.options, card.value, lambda v: Start.set_value(card.key, v), width=width),
        rx.cond(
            card.discovery != "", rx.text(card.discovery, **MONO, color=T.DIM, font_size=SMALL), rx.fragment()
        ),
        spacing="3",
        align="center",
    )


def card_view(card: Card) -> rx.Component:
    """A universal setting: the name and its control on one line, the description under them."""
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
    return rx.vstack(
        rx.hstack(
            rx.text(card.name, font_weight="700", font_size=BODY, min_width="170px"),
            rx.box(control, flex="1"),
            width="100%",
            align="center",
            spacing="4",
        ),
        rx.text(
            card.description,
            color=T.MUTED,
            font_size=SMALL,
            line_height="1.45",
            width="100%",
            margin_top=T.SPACE["sm"],
        ),
        **CARD,
        align="start",
        spacing="1",
    )


HUE_MATCH = [(k, v) for k, v in T.STAGE_HUES.items()]
GLASS_FILL = [(k, T.tint(k, 0.10)) for k in T.STAGE_HUES]
GLASS_STROKE = [(k, f"1px solid {T.tint(k, 0.55)}") for k in T.STAGE_HUES]


def side_row(model: Card, effort: Card) -> rx.Component:
    """One block per side of a stage, centred under the box: the side's glyph and what it does
    here, then Name over the model dropdown, then Effort over the effort dropdown."""
    color = rx.cond(model.side == "author", T.ACTOR["a"], T.ACTOR["b"])
    glyph = rx.cond(model.side == "author", "✳", "☘")
    return rx.vstack(
        rx.hstack(
            rx.text(glyph, color=color, font_size=BODY),
            rx.text(
                model.func,
                font_weight="700",
                font_size=BODY,
                text_align="center",
                white_space="nowrap",
                overflow="hidden",
                text_overflow="ellipsis",
            ),
            spacing="2",
            align="center",
            justify="center",
            width="100%",
        ),
        centered_select(model.options, model.value, lambda v: Start.set_value(model.key, v)),
        centered_select(effort.options, effort.value, lambda v: Start.set_value(effort.key, v)),
        spacing="1",
        width="86%",
        align="center",
        padding=f"{T.SPACE['sm']} 0",
        margin="0 auto",
    )


def stage_column(t: Tile) -> rx.Component:
    """The stage's glass box (the run page's colour code), then a writer row and a checker row,
    each a model dropdown and its effort side by side."""
    hue = rx.match(t.hue, *HUE_MATCH, T.MUTED)
    cards = Start.stage_cards[t.id]
    return rx.vstack(
        rx.box(
            rx.vstack(
                rx.text(f"{t.n} · {t.emoji}", **MONO, color=hue, font_size=SMALL),
                rx.text(t.title, font_weight="700", font_size=f"{T.SIZE['title']}px", color=T.TEXT),
                spacing="1",
                align="center",
            ),
            border=rx.match(t.hue, *GLASS_STROKE, f"1px solid {T.BORDER}"),
            background=rx.match(t.hue, *GLASS_FILL, T.CARD),
            border_radius=T.RADIUS["box"],
            padding=T.SPACE["md"],
            width="100%",
        ),
        rx.cond(cards.length() >= 2, side_row(cards[0], cards[1]), rx.fragment()),
        rx.cond(cards.length() >= 4, side_row(cards[2], cards[3]), rx.fragment()),
        spacing="3",
        width="100%",
        flex="1 1 0",
        min_width="0",
        align="start",
    )


def side_column(cards, side: str, title: str) -> rx.Component:
    """A side's column above the rail: the glyph and title, then backend, model, effort."""
    color = T.ACTOR["a"] if side == "author" else T.ACTOR["b"]
    glyph = "✳" if side == "author" else "☘"
    return rx.vstack(
        rx.hstack(
            rx.text(glyph, color=color, font_size=BODY),
            rx.text(title, font_weight="700", font_size=BODY, text_align="center", white_space="nowrap"),
            spacing="2",
            align="center",
            justify="center",
            width="100%",
        ),
        rx.foreach(cards, lambda c: centered_select(c.options, c.value, lambda v: Start.set_value(c.key, v))),
        spacing="2",
        width="210px",
        align="center",
        margin="0 auto",
        padding=f"{T.SPACE['sm']} 0",
    )


def run_column(card: Card) -> rx.Component:
    """Running mode or attack rounds: a centred column with the title, the dropdown, its reason."""
    return rx.vstack(
        rx.text(card.name, font_weight="700", font_size=BODY, text_align="center", white_space="nowrap"),
        rx.box(
            centered_select(card.options, card.value, lambda v: Start.set_value(card.key, v)), width="210px"
        ),
        rx.text(
            card.description,
            color=T.MUTED,
            font_size=SMALL,
            line_height="1.45",
            text_align="center",
            max_width="520px",
        ),
        spacing="2",
        width="100%",
        align="center",
        flex="1 1 0",
        min_width="0",
        padding=f"{T.SPACE['sm']} 0",
    )


def run_card() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text("The run.", font_weight="700", font_size=BODY),
            rx.text(
                "How much it asks of you, and how many attack rounds it spends.",
                color=T.MUTED,
                font_size=BODY,
            ),
            spacing="2",
        ),
        rx.hstack(
            rx.foreach(Start.run_cards, run_column),
            spacing="6",
            width="100%",
            align="start",
            margin_top=T.SPACE["md"],
        ),
        **CARD,
    )


def sides_card() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text("The two sides.", font_weight="700", font_size=BODY),
            rx.text(
                "Backend, model and effort for the author and the checker; every stage row below inherits these unless it says otherwise.",
                color=T.MUTED,
                font_size=BODY,
            ),
            spacing="2",
        ),
        rx.hstack(
            side_column(Start.author_cards, "author", "Author"),
            rx.box(width="64px"),
            side_column(Start.checker_cards, "checker", "Checker"),
            spacing="6",
            width="100%",
            align="center",
            margin_top=T.SPACE["md"],
        ),
        **CARD,
    )


def stages_rail() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text("Per stage.", font_weight="700", font_size=BODY),
            rx.text(
                "Which model and effort each side uses on each stage; `as author` and `as checker` inherit the rows above.",
                color=T.MUTED,
                font_size=BODY,
            ),
            spacing="2",
        ),
        rx.hstack(
            rx.foreach(Start.tiles, stage_column),
            spacing="3",
            width="100%",
            align="start",
            margin_top=T.SPACE["md"],
        ),
        **CARD,
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
            rx.foreach(Start.brief_cards, card_view),
            run_card(),
            sides_card(),
            stages_rail(),
            rx.hstack(
                rx.button(
                    "Start the run ▸",
                    on_click=Start.start,
                    disabled=~Start.ready,
                    color_scheme="gray",
                    variant="solid",
                ),
                rx.text(Start.blocking, color=T.MUTED, font_size=SMALL),
                spacing="3",
                align="center",
            ),
            rx.cond(Start.error != "", rx.text(Start.error, color=T.BAD, font_size=SMALL), rx.fragment()),
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
            padding=T.SPACE["lg"],
        ),
        width="100%",
    )
