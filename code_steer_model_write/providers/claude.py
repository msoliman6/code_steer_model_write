"""The Claude providers. For the API-backed sides (`anthropic`, `agent_sdk`) the Anthropic
Models API is the catalogue when a key works: `client.models.list()` returns id, display name
and a capabilities object; efforts come from the model family (the API states no effort list).
For `claude_cli` a maintained table: Claude Code exposes no machine-readable catalogue; its
`--model` takes an alias or id and `--effort` a level. When it grows one, only this file changes."""

from __future__ import annotations

from functools import lru_cache

from .base import ModelInfo

# Claude Code's effort ladder (--effort) and the API's output_config.effort: the top rungs are
# what the frontier families accept; Haiku stops at high.
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
EFFORTS_HAIKU = ["low", "medium", "high"]

CLAUDE_MODELS: list[ModelInfo] = [
    ModelInfo(id="claude-fable-5-1", name="Claude Fable 5.1", efforts=EFFORTS, default_effort="high"),
    ModelInfo(id="claude-opus-5", name="Claude Opus 5", efforts=EFFORTS, default_effort="high"),
    ModelInfo(id="claude-sonnet-5", name="Claude Sonnet 5", efforts=EFFORTS, default_effort="medium"),
    ModelInfo(id="claude-haiku-4-5", name="Claude Haiku 4.5", efforts=EFFORTS_HAIKU, default_effort="low"),
]


def _efforts_for_id(model_id: str) -> tuple[list[str], str]:
    if "haiku" in model_id:
        return EFFORTS_HAIKU, "low"
    if "sonnet" in model_id:
        return EFFORTS, "medium"
    return EFFORTS, "high"


@lru_cache(maxsize=1)
def _api_catalog() -> list[ModelInfo]:
    """`client.models.list()`; empty when there is no working key (the caller falls back)."""
    try:
        import anthropic

        client = anthropic.Anthropic()
        out: list[ModelInfo] = []
        for m in client.models.list():
            mid = getattr(m, "id", "")
            if not mid.startswith("claude-"):
                continue
            efforts, default = _efforts_for_id(mid)
            caps = getattr(m, "capabilities", None)
            if (
                caps is not None
                and not getattr(caps, "effort", True)
                and not (isinstance(caps, dict) and caps.get("effort", True))
            ):
                efforts, default = [], ""
            out.append(
                ModelInfo(
                    id=mid,
                    name=getattr(m, "display_name", mid),
                    efforts=efforts,
                    default_effort=default or None,
                )
            )
        return out
    except Exception:  # noqa: BLE001 -- no key, no network: the table answers
        return []


class ClaudeProvider:
    """`claude_cli`: the configured table."""

    name = "claude"
    model_discovery = "configured"
    effort_discovery = "configured"

    def list_models(self) -> list[ModelInfo]:
        return list(CLAUDE_MODELS)

    def default_model(self) -> str:
        return "claude-sonnet-5"


class ClaudeApiProvider(ClaudeProvider):
    """`anthropic` / `agent_sdk`: the Models API when it answers, else the table."""

    name = "claude_api"

    @property
    def model_discovery(self) -> str:  # type: ignore[override]
        return "dynamic" if _api_catalog() else "configured"

    effort_discovery = "configured"

    def list_models(self) -> list[ModelInfo]:
        return _api_catalog() or list(CLAUDE_MODELS)
