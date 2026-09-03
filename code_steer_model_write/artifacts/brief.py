"""The brief: what the human wants, in their words, checked by code for the words that make
a request unfalsifiable (rules 2, 11)."""

from __future__ import annotations

from pydantic import Field

from ..spec.base import Artifact


class Brief(Artifact):
    request: str = Field(min_length=10, description="what to build, one paragraph, in the human's words")
    context: str = Field(default="", description="where it runs, who calls it, what exists already")
    surface: str = Field(
        default="", description="the public surface: a module, a CLI, an endpoint, a library"
    )
    must_be_true: list[str] = Field(
        default_factory=list, description="observable claims the result must satisfy"
    )
    constraints: list[str] = Field(default_factory=list, description="language, dependencies, limits")
    out_of_scope: list[str] = Field(
        default_factory=list, description="a boundary, not a suggestion: never a unit, never a step"
    )
    known_reference: str = Field(default="", description="prior art or a spec the result must agree with")
    language: str = Field(default="python", description="the implementation language (python in v1)")
    module: str = Field(default="", description="the importable module name the surface lives in")
