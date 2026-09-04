"""The seams (ARCHITECTURE.md section 6): one interface per layer, the existing behaviour as
each one's first implementation. A tool is chosen behind an interface, never in front of one.

`Layers` is the set a run executes through; `default_layers()` builds the first
implementations. Nothing here decides sequence: the Driver has no seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .policy import Identity, Policy, RunIdentity, StepPolicy
from .rails import Rails, SchemaRails
from .sandbox import Sandbox, SubprocessSandbox
from .stores import ArtifactStore, MemoryStore, NoMemory, StateStore
from .tools import ToolRegistry, default_registry

if TYPE_CHECKING:
    from ..events import EventLog
    from ..state.run import RunPaths


@dataclass
class Layers:
    """What one run executes through. Built once per process; the runner and the checks read
    it through `current()`."""

    identity: Identity
    policy: Policy
    rails: Rails
    sandbox: Sandbox
    tools: ToolRegistry
    memory: MemoryStore = field(default_factory=NoMemory)


_current: Layers | None = None


def default_layers(paths: "RunPaths | None" = None, events: "EventLog | None" = None) -> Layers:
    """The first implementations: principals from the RunSpec, the recipe's own rules as
    policy, schema plus semantic checks as rails, a subprocess sandbox, the four code tools."""
    sandbox = SubprocessSandbox(events=events)
    return Layers(
        identity=RunIdentity(paths),
        policy=StepPolicy(events=events),
        rails=SchemaRails(events=events),
        sandbox=sandbox,
        tools=default_registry(sandbox, events=events),
    )


def install(layers: Layers) -> Layers:
    """Make `layers` the process's current set (the runner installs its own at begin)."""
    global _current
    _current = layers
    return layers


def current() -> Layers:
    """The current set, or the defaults with no event log (a check run outside a runner)."""
    global _current
    if _current is None:
        _current = default_layers()
    return _current


__all__ = [
    "ArtifactStore",
    "Identity",
    "Layers",
    "MemoryStore",
    "Policy",
    "Rails",
    "Sandbox",
    "StateStore",
    "ToolRegistry",
    "current",
    "default_layers",
    "install",
]
