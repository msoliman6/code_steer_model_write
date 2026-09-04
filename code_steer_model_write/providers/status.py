"""Each backend's readiness, from the same facts the doctor checks (rule 4): a pill for the
Providers view, never a second opinion."""

from __future__ import annotations

import os
import shutil
from typing import Literal

from pydantic import BaseModel

from . import registry

State = Literal["configured", "missing_key", "not_on_path", "not_connected"]


class BackendStatus(BaseModel):
    backend: str
    provider: str
    state: State
    pill: str  # CONFIGURED | MISSING KEY | NOT ON PATH | NOT CONNECTED
    requirement: str  # the env var or the executable, in mono
    discovery: str  # dynamic | configured
    models: int


def status_for(backend: str) -> BackendStatus:
    prov = registry.for_backend(backend)
    n = len(prov.list_models())
    disc = prov.model_discovery
    if backend == "claude_cli":
        ok = bool(shutil.which("claude"))
        return BackendStatus(
            backend=backend,
            provider=prov.name,
            state="configured" if ok else "not_on_path",
            pill="CONFIGURED" if ok else "NOT ON PATH",
            requirement="claude (its own login; CSMW_CLI_USE_LOGIN=1)",
            discovery=disc,
            models=n,
        )
    if backend == "codex_cli":
        ok = bool(shutil.which("codex"))
        return BackendStatus(
            backend=backend,
            provider=prov.name,
            state="configured" if ok else "not_on_path",
            pill="CONFIGURED" if ok else "NOT ON PATH",
            requirement="codex (its own login)",
            discovery=disc,
            models=n,
        )
    if backend in ("anthropic", "agent_sdk"):
        ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        return BackendStatus(
            backend=backend,
            provider=prov.name,
            state="configured" if ok else "missing_key",
            pill="CONFIGURED" if ok else "MISSING KEY",
            requirement="ANTHROPIC_API_KEY",
            discovery=disc,
            models=n,
        )
    if backend == "litellm":
        keys = [k for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(k)]
        return BackendStatus(
            backend=backend,
            provider=prov.name,
            state="configured" if keys else "missing_key",
            pill="CONFIGURED" if keys else "MISSING KEY",
            requirement=", ".join(keys) or "OPENAI_API_KEY / GEMINI_API_KEY / …",
            discovery=disc,
            models=n,
        )
    return BackendStatus(
        backend=backend,
        provider=prov.name,
        state="configured",
        pill="CONFIGURED",
        requirement="FAKE_MODELS=1",
        discovery=disc,
        models=n,
    )


def all_statuses() -> list[BackendStatus]:
    return [status_for(b) for b in ("claude_cli", "codex_cli", "anthropic", "agent_sdk", "litellm", "fake")]


def refresh_catalogues() -> None:
    from .claude import _api_catalog
    from .codex import _catalog

    _catalog.cache_clear()
    _api_catalog.cache_clear()
