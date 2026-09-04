"""The two sides' marks (round two: logos). The author's is the Claude mark the user pasted,
served from assets/; the checker's stays a glyph until its mark arrives."""

from __future__ import annotations

import reflex as rx


def author_mark(size: str = "16px") -> rx.Component:
    return rx.image(src="/claude-64.png", width=size, height=size, flex_shrink="0", alt="Claude")


def checker_mark(size: str = "16px") -> rx.Component:
    return rx.image(src="/codex-64.png", width=size, height=size, flex_shrink="0", alt="Codex")


def side_mark(is_author, size: str = "16px") -> rx.Component:
    """`is_author` may be a Var: the author's mark or the checker's."""
    return rx.cond(is_author, author_mark(size), checker_mark(size))
