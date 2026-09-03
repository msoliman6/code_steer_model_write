"""Backend name -> provider. The page asks the registry; it never sees a CLI's syntax."""

from __future__ import annotations

from .base import ModelInfo, Provider
from .claude import ClaudeApiProvider, ClaudeProvider
from .codex import CodexProvider


class LiteLLMProvider:
    name = "litellm"
    model_discovery = "configured"
    effort_discovery = "configured"

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id="gpt-5.4-mini",
                name="gpt-5.4-mini (openai)",
                efforts=["low", "medium", "high"],
                default_effort="medium",
            ),
            ModelInfo(
                id="gemini/gemini-2.5-pro",
                name="Gemini 2.5 Pro",
                efforts=["low", "medium", "high"],
                default_effort="medium",
            ),
            ModelInfo(
                id="anthropic/claude-sonnet-5",
                name="Claude Sonnet 5 (via litellm)",
                efforts=["low", "medium", "high"],
                default_effort="medium",
            ),
        ]

    def default_model(self) -> str:
        return "gpt-5.4-mini"


class FakeProvider:
    name = "fake"
    model_discovery = "configured"
    effort_discovery = "configured"

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id="fake-a", name="fake author", efforts=["low"], default_effort="low"),
            ModelInfo(id="fake-b", name="fake checker", efforts=["low"], default_effort="low"),
        ]

    def default_model(self) -> str:
        return "fake-a"


_PROVIDERS: dict[str, Provider] = {
    "codex": CodexProvider(),
    "claude": ClaudeProvider(),
    "claude_api": ClaudeApiProvider(),
    "litellm": LiteLLMProvider(),
    "fake": FakeProvider(),
}
BACKEND_PROVIDER = {
    "codex_cli": "codex",
    "claude_cli": "claude",
    "anthropic": "claude_api",
    "agent_sdk": "claude_api",
    "litellm": "litellm",
    "fake": "fake",
}

PROVIDER_CAPABILITIES = {
    n: {"model_discovery": p.model_discovery, "effort_discovery": p.effort_discovery}
    for n, p in _PROVIDERS.items()
}


def for_backend(backend: str) -> Provider:
    return _PROVIDERS[BACKEND_PROVIDER.get(backend, "fake")]


def get(name: str) -> Provider:
    return _PROVIDERS[name]
