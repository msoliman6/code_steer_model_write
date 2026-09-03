"""Recipe registry: name -> class. A TaskSpec's `recipe` resolves here."""

from __future__ import annotations

from .base import Recipe


def get(name: str) -> Recipe:
    if name == "code_builder":
        from .code_builder.recipe import CodeBuilder

        return CodeBuilder()
    if name == "debate":
        from .debate.recipe import Debate

        return Debate()
    if name == "toy":
        raise KeyError("toy is a test program, not a recipe")
    raise KeyError(f"no recipe named {name!r}; known: {names()}")


def names() -> list[str]:
    return ["code_builder", "debate"]
