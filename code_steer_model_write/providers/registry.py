"""Backend name -> provider. The page asks the registry; it never sees a CLI's syntax."""

from __future__ import annotations

from .base import ModelInfo, Provider
from .claude import ClaudeApiProvider, ClaudeProvider
from .codex import CodexProvider


class PydanticAIProvider:
    """Any provider through PydanticAI (ARCHITECTURE.md 7.5), `provider:model`; the API path,
    for deployments that have keys."""

    name = "pydantic_ai"
    model_discovery = "configured"
    effort_discovery = "configured"

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id="anthropic:claude-sonnet-5",
                name="Claude Sonnet 5 (Anthropic API)",
                efforts=["low", "medium", "high"],
                default_effort="medium",
            ),
            ModelInfo(
                id="anthropic:claude-haiku-4-5",
                name="Claude Haiku 4.5 (Anthropic API)",
                efforts=["low", "medium", "high"],
                default_effort="low",
            ),
            ModelInfo(
                id="openai:gpt-5.4-mini",
                name="gpt-5.4-mini (OpenAI API)",
                efforts=["low", "medium", "high"],
                default_effort="medium",
            ),
        ]


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
    "pydantic_ai": PydanticAIProvider(),
    "fake": FakeProvider(),
}
BACKEND_PROVIDER = {
    "codex_cli": "codex",
    "claude_cli": "claude",
    "anthropic": "claude_api",
    "agent_sdk": "claude_api",
    "pydantic_ai": "pydantic_ai",
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
