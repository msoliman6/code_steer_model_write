"""The Codex provider: `codex debug models` is the catalogue (dynamic model and effort
discovery); `--bundled` is the fallback; a small table is the last resort when the CLI is not
on PATH, so the page still renders. Cached for the process."""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache

from .base import ModelInfo

FALLBACK = [
    ModelInfo(
        id="gpt-5.5", name="GPT-5.5", efforts=["low", "medium", "high", "xhigh"], default_effort="medium"
    ),
    ModelInfo(
        id="gpt-5.4", name="GPT-5.4", efforts=["low", "medium", "high", "xhigh"], default_effort="medium"
    ),
    ModelInfo(
        id="gpt-5.4-mini",
        name="GPT-5.4-Mini",
        efforts=["low", "medium", "high", "xhigh"],
        default_effort="medium",
    ),
]


def parse_catalog(text: str) -> list[ModelInfo]:
    data = json.loads(text)
    items = data.get("models", data) if isinstance(data, dict) else data
    out: list[ModelInfo] = []
    for m in items:
        if m.get("visibility", "list") != "list":
            continue
        out.append(
            ModelInfo(
                id=m["slug"],
                name=m.get("display_name", m["slug"]),
                efforts=[lv["effort"] for lv in m.get("supported_reasoning_levels", []) if lv.get("effort")],
                default_effort=m.get("default_reasoning_level"),
            )
        )
    return out


@lru_cache(maxsize=2)
def _catalog(bundled: bool) -> list[ModelInfo]:
    if not shutil.which("codex"):
        return []
    cmd = ["codex", "debug", "models"] + (["--bundled"] if bundled else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        return parse_catalog(r.stdout)
    except (subprocess.TimeoutExpired, ValueError, KeyError):
        return []


class CodexProvider:
    name = "codex"
    model_discovery = "dynamic"
    effort_discovery = "dynamic"

    def list_models(self) -> list[ModelInfo]:
        return _catalog(False) or _catalog(True) or list(FALLBACK)

    def default_model(self) -> str:
        ms = self.list_models()
        mini = next((m.id for m in ms if m.id.endswith("mini")), None)
        return mini or ms[0].id
