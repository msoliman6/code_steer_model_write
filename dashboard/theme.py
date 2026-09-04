"""Every colour, size and spacing on the page is a token here (docs/PLAN.md §7a; rule 4).
No literal in a component. The stage and actor hues are the figure's (code_steer_model_write/figure.py)."""

from __future__ import annotations

SURFACE = "#0f1113"
CARD = "#16191d"
BORDER = "#262a30"
BORDER_STRONG = "#3a3f47"
TEXT = "#e6edf3"
MUTED = "#9aa4ae"
DIM = "#6e7681"
WHITE = "#ffffff"

OK = "#3fb950"
WARN = "#d4a72c"
BAD = "#e06661"
LIVE = "#8b949e"  # no accent colour: selection is contrast; the stage hue is the only living colour

STAGE_HUES: dict[str, str] = {
    "blue": "#6ea6e8",
    "gold": "#d69a26",
    "violet": "#b28ae8",
    "teal": "#43bdb2",
    "red": "#e06661",
    "slate": "#9aa4ae",
}
STAGE_RGB: dict[str, tuple[int, int, int]] = {
    "blue": (77, 143, 220),
    "gold": (187, 128, 9),
    "violet": (154, 110, 224),
    "teal": (47, 163, 154),
    "red": (208, 74, 69),
    "slate": (139, 148, 158),
}
ACTOR: dict[str, str] = {"a": "#db6d28", "b": "#2fa39a", "you": "#d4a72c", "code": "#8b949e"}
ACTOR_GLYPH: dict[str, str] = {"a": "✳", "b": "☘", "you": "◆", "code": "·"}

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

# the five-step type scale (px); CSMW_BASE shifts all of them
BASE = 15
SIZE = {"eyebrow": 14, "body": 16, "title": 18, "headline": 22, "page": 30}
LETTER_SPACING_EYEBROW = "0.08em"

SPACE = {"xs": "4px", "sm": "8px", "md": "12px", "lg": "20px", "xl": "32px"}
RADIUS = {"card": "12px", "box": "10px", "chip": "999px"}
PAGE_WIDTH = "1140px"
POLL_SECONDS = 3


# run status dot (the runs tabs): one colour per state
STATUS_DOT: dict[str, str] = {
    "running": OK,  # green: working
    "waiting": WARN,  # amber: a gate is waiting for you
    "halted": BAD,  # red: halted honestly (resumable) or broke
    "done": DIM,  # grey: finished; a clean verdict gets a green ring, carried items an amber ring
    "queued": DIM,
}


def k(n: int | float) -> str:
    """Tokens in K and M: 25.2K, 1.3M; under a thousand as is."""
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K" if n < 100_000 else f"{n / 1_000:.0f}K"
    return f"{int(n)}"


SUBCARD = "#1c2026"  # a card inside a card
SEL_FILL = "#262b32"  # the selected row: contrast, not a hue
SEL_BORDER = "#464c55"
SIDEBAR_W = "240px"
PILL = {  # the status pills: uppercase mono on a faint tint
    "ok": ("#3fb950", "rgba(63,185,80,0.14)"),
    "warn": ("#d4a72c", "rgba(212,167,44,0.14)"),
    "bad": ("#e06661", "rgba(224,102,97,0.14)"),
    "neutral": ("#9aa4ae", "rgba(154,164,174,0.12)"),
}


def tint(hue: str, alpha: float) -> str:
    r, g, b = STAGE_RGB[hue]
    return f"rgba({r},{g},{b},{alpha})"


TOKENS: set[str] = {
    SURFACE,
    CARD,
    BORDER,
    BORDER_STRONG,
    TEXT,
    MUTED,
    DIM,
    WHITE,
    OK,
    WARN,
    BAD,
    LIVE,
    *STAGE_HUES.values(),
    *ACTOR.values(),
}
