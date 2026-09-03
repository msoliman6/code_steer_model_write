"""Every colour, size and spacing on the page is a token here (docs/PLAN.md §7a; rule 4).
No literal in a component. The stage and actor hues are the figure's (code_steer_model_write/figure.py)."""

from __future__ import annotations

SURFACE = "#0d1117"
CARD = "#0f141b"
BORDER = "#252832"
BORDER_STRONG = "#3a3f4b"
TEXT = "#e6edf3"
MUTED = "#9aa4ae"
DIM = "#6e7681"
WHITE = "#ffffff"

OK = "#3fb950"
WARN = "#d4a72c"
BAD = "#e06661"
LIVE = "#58a6ff"

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
BASE = 13
SIZE = {"eyebrow": 11, "body": 13, "title": 15, "headline": 18, "page": 28}
LETTER_SPACING_EYEBROW = "0.08em"

SPACE = {"xs": "4px", "sm": "8px", "md": "12px", "lg": "20px", "xl": "32px"}
RADIUS = {"card": "12px", "box": "10px", "chip": "999px"}
PAGE_WIDTH = "1140px"
POLL_SECONDS = 3


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
