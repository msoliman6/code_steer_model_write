"""The profile (ARCHITECTURE.md section 5): what a workflow optimizes for, as settings the
layers read. The runtime holds the shape and the correctness profile as the reference
(profiles/CORRECTNESS.md in the architecture repo); a workflow may declare its own.

Only the settings the built layers read are here; the rest of P1..P14 arrive with their
layers. Nothing in section 4 is a setting: a profile cannot turn off the schema, the log, the
walk, or the policy point."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Profile(BaseModel):
    name: str
    # P7 -- separation of duties: the checker must be another vendor where possible
    other_vendor: bool = True
    # P8 -- tool allowance: the closed list a tool-using step may declare; empty = no tool-using steps
    tools_allowed: list[str] = Field(default_factory=list)
    # P9 -- sandbox default per step kind
    sandbox_tier: Literal["subprocess", "container"] = "subprocess"
    # P10 -- rails beyond the schema: Guardrails AI validators by registered name, per hook
    rails_before_prompt: list[str] = Field(default_factory=list)
    rails_after_answer: list[str] = Field(default_factory=list)
    # which policy engine decides (both embedded; "step" is the runtime's own rules, the walk's fallback)
    policy_engine: Literal["cedar", "step"] = "cedar"


CORRECTNESS = Profile(name="correctness")
"""The reference profile: schema plus the existing checks, no validator beyond them, no
tools, the subprocess tier by default (the container tier is phase 7), Cedar deciding."""
