"""The seams (ARCHITECTURE.md section 6): one interface per layer, the existing behaviour as
each one's first implementation. A tool is chosen behind an interface, never in front of one.

`Layers` is the set a run executes through; `default_layers()` builds the first
implementations. Nothing here decides sequence: the Driver has no seam.
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .policy import Identity, Policy, RunIdentity, StepPolicy
from .profile import CORRECTNESS, Profile
from .rails import Rails
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
    profile: Profile = field(default_factory=lambda: CORRECTNESS)

    def installed(self) -> dict[str, str]:
        """What sits behind each seam, for the record (`layers.installed` event)."""
        return {
            "profile": self.profile.name,
            "policy": getattr(self.policy, "engine", type(self.policy).__name__),
            "rails": getattr(self.rails, "tool", type(self.rails).__name__),
            "sandbox": getattr(self.sandbox, "tier", type(self.sandbox).__name__),
            "tools": ",".join(self.tools.names()),
            "memory": type(self.memory).__name__,
        }


_current: Layers | None = None


def default_layers(
    paths: "RunPaths | None" = None, events: "EventLog | None" = None, profile: Profile = CORRECTNESS
) -> Layers:
    """The first implementations behind each seam, chosen by the profile: Cedar as the policy
    engine (the runtime's own rules as the fallback the profile may name), Guardrails AI
    behind the rails, a subprocess sandbox, the four code tools. Every choice is in-process."""
    sandbox: Sandbox
    tier = os.environ.get(
        "CSMW_SANDBOX", profile.sandbox_tier
    )  # the operator's dial over the profile's default
    sandbox_note = ""
    if tier == "container":
        from . import container_sandbox

        ok, why = container_sandbox.available()
        if ok:
            sandbox = container_sandbox.ContainerSandbox(
                events=events, mount_root=paths.run_dir if paths else None
            )
        else:  # the fallback is a fact in the record, never a silent downgrade
            sandbox = SubprocessSandbox(events=events)
            sandbox_note = f"container asked for, not available ({why}); subprocess tier"
            print(f"sandbox: {sandbox_note}")
    else:
        sandbox = SubprocessSandbox(events=events)
    tools = default_registry(sandbox, events=events)
    policy: Policy
    if profile.policy_engine == "cedar":
        from .cedar_policy import CedarPolicy

        policy = CedarPolicy(events=events, tools=tools.names())
    else:
        policy = StepPolicy(events=events)
    from .guardrails_rails import GuardrailsRails

    layers = Layers(
        identity=RunIdentity(paths),
        policy=policy,
        rails=GuardrailsRails(events=events, profile=profile),
        sandbox=sandbox,
        tools=tools,
        profile=profile,
    )
    if events is not None:
        installed: dict[str, Any] = dict(layers.installed())
        if sandbox_note:
            installed["sandbox_note"] = sandbox_note
        events.append("layers.installed", **installed)
    return layers


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
    "CORRECTNESS",
    "Profile",
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
