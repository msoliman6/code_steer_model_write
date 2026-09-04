"""Recipe registry: name -> Recipe. The bundled recipes plus every installed package that
declares a `csmw.recipes` entry point; a project repo registers its recipe there and the CLI,
the start page and the run page know it without a line changing here (plan §12). Walk legs
arrive the same way through `csmw.walk_legs`. A TaskSpec's `recipe` resolves here."""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Callable

from .base import Recipe

# the bundled recipes: module path and class name; the debate is the template's own example
_BUILTIN: dict[str, tuple[str, str]] = {
    "code_builder": ("code_steer_model_write.recipes.code_builder.recipe", "CodeBuilder"),
    "debate": ("code_steer_model_write.recipes.debate.recipe", "Debate"),
}


@lru_cache(maxsize=1)
def _installed() -> dict[str, EntryPoint]:
    """Installed recipe packages, by entry-point name. Cached: the set cannot change while the
    process lives."""
    return {ep.name: ep for ep in entry_points(group="csmw.recipes")}


def get(name: str) -> Recipe:
    if name == "toy":
        raise KeyError("toy is a test program, not a recipe")
    ep = _installed().get(name)
    if ep is not None:  # an installed project wins over a bundled recipe of the same name
        obj: Any = ep.load()
        return obj if hasattr(obj, "spec") else obj()  # an instance, a class or a factory
    if name in _BUILTIN:
        module, cls = _BUILTIN[name]
        return getattr(import_module(module), cls)()
    raise KeyError(f"no recipe named {name!r}; known: {names()}")


def names() -> list[str]:
    """Installed project recipes first, then the bundled ones."""
    inst = list(_installed())
    return [*inst, *(n for n in _BUILTIN if n not in inst)]


def default_name() -> str:
    """The recipe the start page opens on: the installed project's, else the first bundled one."""
    return names()[0]


def walk_legs() -> dict[str, dict[str, Callable[..., str]]]:
    """Walk legs contributed by installed packages: entry point `csmw.walk_legs`, one per recipe,
    loading to a {leg name: function} dict (walk.py merges them with its own)."""
    out: dict[str, dict[str, Callable[..., str]]] = {}
    for ep in entry_points(group="csmw.walk_legs"):
        legs = ep.load()
        if isinstance(legs, dict):
            out[ep.name] = legs
    return out
