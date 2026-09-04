"""Settings and constants -- the one owner of every knob (rule 4).

Prompt sentences, docs and walk probes derive their numbers from here; nothing restates them.
"""

from __future__ import annotations

import os
from pathlib import Path

import json

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- constants (rule 6, 8, 14) ------------------------------------------------------------

RE_ASK_MAX = 6  # a refused answer is re-asked at most this many times (rule 6)
MAX_TURNS = 3  # an author call may take this many turns (it needs one; rule 14)
STALL_SECONDS = 180  # no fact from the model for this long is a stall (rule 10)
ROUNDS_DEFAULT = 2  # review rounds cap, set once per run (rule 8)
LEDGER_MAX_ROWS = 30  # assumptions ledger bound (rule 11)
MIN_ARGUMENT_WORDS = 12  # an arbitration must engage the argument (rule 7)

# The lint rule set the pipeline applies to agent-written code. Owned here, never by a
# project's pyproject (rule 4).
RUFF_SELECT = ["E4", "E7", "E9", "F", "B"]
RUFF_IGNORE = ["E741", "E731"]


class Mode(StrEnum):
    DETAILED = "detailed"  # every question asked
    LIGHT = "light"  # only the risky ones
    AUTO = "auto"  # none; every answer defaulted and flagged


class BackendName(StrEnum):
    ANTHROPIC = "anthropic"
    AGENT_SDK = "agent_sdk"
    LITELLM = "litellm"
    CLAUDE_CLI = "claude_cli"
    CODEX_CLI = "codex_cli"
    FAKE = "fake"


VENDOR_OF: dict[BackendName, str] = {
    BackendName.ANTHROPIC: "anthropic",
    BackendName.AGENT_SDK: "anthropic",
    BackendName.CLAUDE_CLI: "anthropic",
    BackendName.CODEX_CLI: "openai",
    BackendName.LITELLM: "litellm",  # vendor is the model's; resolved by model name
    BackendName.FAKE: "fake",
}


def vendor_of(backend: BackendName, model: str) -> str:
    if backend is BackendName.LITELLM:
        head = model.split("/", 1)[0].lower()
        return head if "/" in model else ("openai" if model.startswith(("gpt", "o")) else head)
    return VENDOR_OF[backend]


Effort = Literal["low", "medium", "high", "xhigh", "max"]


class RoleSpec(BaseModel):
    """Which backend and model answer for a role, and how hard they think (rule 14)."""

    backend: BackendName
    model: str
    effort: Effort = "medium"
    thinking: bool = False

    @property
    def vendor(self) -> str:
        return vendor_of(self.backend, self.model)


class Settings(BaseSettings):
    """Environment-backed settings. `.env` is read; `CSMW_` is the prefix."""

    model_config = SettingsConfigDict(env_prefix="CSMW_", env_file=".env", extra="ignore")

    backend: BackendName = BackendName.FAKE
    model_a: str = "claude-sonnet-5"
    model_b: str = "gpt-5.4-mini"
    backend_b: BackendName | None = None  # None: the checker uses the same backend kind
    mode: Mode = Mode.LIGHT
    rounds: int = Field(default=ROUNDS_DEFAULT, ge=1, le=6)
    runs_dir: str = "runs"
    mlflow_tracking_uri: str = "sqlite:///mlflow.db"
    stall_seconds: int = STALL_SECONDS

    def role_a(self) -> RoleSpec:
        return RoleSpec(backend=self.backend, model=self.model_a)

    def role_b(self) -> RoleSpec:
        return RoleSpec(backend=self.backend_b or self.backend, model=self.model_b)


def review_round_open(n: int, cap: int) -> Literal["answered", "closing", "closed"]:
    """Rounds 1..cap are answered by the author; round cap+1 is the closing read nobody
    answers; beyond that the loop is closed (rule 8)."""
    if n <= cap:
        return "answered"
    if n == cap + 1:
        return "closing"
    return "closed"


# Tokens are the honest measure; a price is looked up on read and may be unknown (rule 14).
# The price of a model is a moving fact, so no table of it is kept here: LiteLLM's model price
# map is the source (it covers every provider and refreshes from the LiteLLM repo on import).
# A prices.json beside the runs dir (or CSMW_PRICES_FILE) overrides it: {"model": [in, out]} in
# USD per million tokens, for a model the map lacks or a rate you negotiated.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {}  # kept for tests and tooling that overlay it


def price_overrides() -> dict[str, tuple[float, float]]:
    """prices.json, read on every call so an edit shows on the next refresh; a broken file
    overrides nothing (the page shows $?, never a wrong number)."""
    table = dict(PRICE_PER_MTOK)
    env = os.environ.get("CSMW_PRICES_FILE")
    candidates = (
        [Path(env)]
        if env
        else [Path("prices.json"), Path(Settings().runs_dir).resolve().parent / "prices.json"]
    )
    for path in candidates:
        if path.exists():
            try:
                for k, v in json.loads(path.read_text()).items():
                    table[str(k)] = (float(v[0]), float(v[1]))
            except (ValueError, TypeError, IndexError):
                pass
    return table


def price_table() -> dict[str, tuple[float, float]]:
    """Kept for callers that want a dict: the overrides only. The map is consulted by price_of."""
    return price_overrides()


def _litellm_price(model: str) -> tuple[float, float, float] | None:
    """(input, output, cached input) in USD per million tokens from LiteLLM's map, or None. The
    model id is tried as given, then with a provider prefix stripped, then by the longest map key
    the id extends (a dated id finds its family)."""
    try:
        import litellm  # noqa: PLC0415 - imported late: a heavy module, only needed on read

        mc = litellm.model_cost
    except Exception:  # noqa: BLE001 - no litellm, no map; the overrides still apply
        return None
    names = [model]
    if "/" in model:
        names.append(model.split("/", 1)[1])
    for n in names:
        e = mc.get(n)
        if not e:
            prefixes = [
                k for k in mc if n.startswith(k + "-") and "/" not in k and "." not in k.split("-")[0]
            ]
            e = mc[max(prefixes, key=len)] if prefixes else None
        if e and "input_cost_per_token" in e and "output_cost_per_token" in e:
            return (
                float(e["input_cost_per_token"]) * 1e6,
                float(e["output_cost_per_token"]) * 1e6,
                float(e.get("cache_read_input_token_cost") or e["input_cost_per_token"]) * 1e6,
            )
    return None


def price_of(model: str) -> tuple[float, float] | None:
    """(input, output) USD per million tokens: the override file first (longest matching key,
    whole dash-separated parts only), then LiteLLM's map."""
    table = price_overrides()
    best = max((k for k in table if model == k or model.startswith(k + "-")), key=len, default=None)
    if best:
        return table[best]
    p = _litellm_price(model)
    return (p[0], p[1]) if p else None


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> float | None:
    """The estimate for one side; cached input at its own rate when the map states one."""
    table = price_overrides()
    best = max((k for k in table if model == k or model.startswith(k + "-")), key=len, default=None)
    if best:
        pin, pout = table[best]
        pcache = pin
    else:
        p = _litellm_price(model)
        if p is None:
            return None
        pin, pout, pcache = p
    return (input_tokens * pin + output_tokens * pout + cache_read_tokens * pcache) / 1_000_000


def usd(x: float | None) -> str:
    """$0.12; $? when the price is unknown, never a zero that lies."""
    if x is None:
        return "$?"
    return f"${x:.2f}" if x >= 0.01 else "$<0.01"
