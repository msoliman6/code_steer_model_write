"""The fake backend's knobs -- every branch a live run can enter, steerable offline (rule 12;
ledger class "a path the walk cannot reach"). Read from the environment once per call so a
walk leg can set them per step.

  FAKE_MODELS=1                    every call answered by the fake
  FAKE_REFUSE=<role>:<n>|same      schema-invalid answers for n attempts, or forever (`same`)
  FAKE_FINDINGS=<role>:<n>:<sev>   a reviewer files n findings of that severity
  FAKE_CLOSING=finding             the closing read files one finding (loop does not converge)
  FAKE_VERDICT=<role>:<value>      a judge/ruler returns this enum value
  FAKE_REVISE=<gate>:<n>           the auto-answerer sends a gate back n times
  FAKE_STALL=<role>                the call emits no fact until the watchdog fires
  FAKE_SCOPE=<role>                the call writes outside its scope root
  FAKE_TOOLLESS_VIOLATION=<role>   the call attempts a tool call on a tool-less step
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def enabled() -> bool:
    return os.environ.get("FAKE_MODELS", "") not in ("", "0", "false")


@dataclass(frozen=True)
class Refuse:
    role: str
    count: int | None  # None = forever


def refuse() -> Refuse | None:
    v = os.environ.get("FAKE_REFUSE", "")
    if not v:
        return None
    role, _, n = v.partition(":")
    return Refuse(role=role, count=None if n in ("same", "") else int(n))


def findings() -> tuple[str, int, str] | None:
    v = os.environ.get("FAKE_FINDINGS", "")
    if not v:
        return None
    role, n, sev = v.split(":")
    return role, int(n), sev


def closing_files_finding() -> bool:
    return os.environ.get("FAKE_CLOSING", "") == "finding"


def verdict() -> tuple[str, str] | None:
    v = os.environ.get("FAKE_VERDICT", "")
    if not v:
        return None
    role, _, val = v.partition(":")
    return role, val


def revise() -> tuple[str, int] | None:
    v = os.environ.get("FAKE_REVISE", "")
    if not v:
        return None
    gate, _, n = v.partition(":")
    return gate, int(n or 1)


def role_flag(name: str) -> str | None:
    return os.environ.get(name) or None
