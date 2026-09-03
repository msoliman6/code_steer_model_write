"""Settings and constants -- the one owner of every knob (rule 4).

Prompt sentences, docs and walk probes derive their numbers from here; nothing restates them.
"""

from __future__ import annotations

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
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    p = PRICE_PER_MTOK.get(model)
    if p is None:
        return None
    return (input_tokens * p[0] + output_tokens * p[1]) / 1_000_000
