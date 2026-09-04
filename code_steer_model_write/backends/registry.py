"""Backend name -> instance (rule 4: config owns the names, this resolves them)."""

from __future__ import annotations

from ..config import BackendName
from .base import Backend


def make(name: str | BackendName) -> Backend:
    n = BackendName(name)
    if n is BackendName.FAKE:
        from .fake import FakeBackend

        return FakeBackend()
    if n is BackendName.ANTHROPIC:
        from .anthropic_api import AnthropicBackend

        return AnthropicBackend()
    if n is BackendName.AGENT_SDK:
        from .agent_sdk import AgentSdkBackend

        return AgentSdkBackend()
    if n is BackendName.LITELLM:
        from .litellm_backend import LiteLLMBackend

        return LiteLLMBackend()
    if n is BackendName.CLAUDE_CLI:
        from .cli import ClaudeCliBackend

        return ClaudeCliBackend()
    if n is BackendName.CODEX_CLI:
        from .cli import CodexCliBackend

        return CodexCliBackend()
    if n is BackendName.PYDANTIC_AI:
        from .pydantic_ai import PydanticAIBackend

        return PydanticAIBackend()
    raise KeyError(name)
