"""Preflight (rule 12): every line it checked is printed; exit 0 ready, 1 warnings, 2 halt.
`FAKE_MODELS=1` skips the vendor probes (the walk, not a preflight); `--deep` runs one walk leg."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .backends import knobs
from .config import Settings

ROOT = Path(__file__).resolve().parent.parent
INSTALL_LINE = 'python3 -m pip install -r requirements.txt'


class Doctor:
    def __init__(self) -> None:
        self.halts: list[str] = []
        self.warns: list[str] = []

    def note(self, line: str) -> None:
        print(f"  {line}")

    def halt(self, line: str) -> None:
        self.halts.append(line)
        print(f"  HALT  {line}")

    def warn(self, line: str) -> None:
        self.warns.append(line)
        print(f"  warn  {line}")


def _requirements() -> list[str]:
    out = []
    for ln in (ROOT / "requirements.txt").read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln.split(">=")[0].split("==")[0].split("[")[0].strip())
    return out


def run(*, deep: bool = False) -> int:
    d = Doctor()
    print(f"code_steer_model_write {__version__}   ({ROOT})")
    fake = knobs.enabled()
    d.note(
        f"models          {'FAKE (FAKE_MODELS): vendor probes skipped -- the offline walk, not a preflight' if fake else 'live'}"
    )
    v = sys.version_info
    (d.note if v >= (3, 11) else d.halt)(
        f"python          {v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 11) else " -- 3.11+ required")
    )
    (d.note if shutil.which("git") else d.halt)(
        "git             " + ("on PATH" if shutil.which("git") else "missing")
    )
    missing = []
    for name in _requirements():
        mod = {
            "pydantic-settings": "pydantic_settings",
            "guardrails-ai": "guardrails",
            "pydantic-ai-slim": "pydantic_ai",
        }.get(name, name)
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            missing.append(name)
    core = [m for m in missing if m in ("pydantic", "pydantic-settings", "jinja2")]
    if core:
        d.halt(f"packages        missing {core}: {INSTALL_LINE}")
    elif missing:
        d.warn(
            f"packages        optional runtime not installed {missing} (the offline walk needs none of them): {INSTALL_LINE}"
        )
    else:
        d.note("packages        every requirement importable")
    try:
        from .layers import default_layers

        inst = default_layers().installed()
        d.note(
            f"layers          policy={inst['policy']} rails={inst['rails']} sandbox={inst['sandbox']} tools={inst['tools']}"
        )
    except Exception as e:  # noqa: BLE001 -- a seam whose tool cannot load is a halt, said in words
        d.halt(f"layers          a seam's tool did not load: {type(e).__name__}: {str(e)[:160]}")
    try:
        from .layers import container_sandbox

        ok, why = container_sandbox.available()
        (d.note if ok else d.warn)(
            f"container       {why}" + ("" if ok else " -- the subprocess tier runs the checks (network on)")
        )
    except Exception as e:  # noqa: BLE001
        d.warn(f"container       {type(e).__name__}: {str(e)[:120]}")
    for tool in ("ruff", "pyright", "pytest"):
        # the same fact the tool uses: pytest runs as `python -m pytest` in this interpreter, the
        # others as the binary beside it, then PATH (`layers.tools.resolve_binary`)
        from .layers.tools import resolve_binary

        found = importlib.util.find_spec("pytest") if tool == "pytest" else resolve_binary(tool)
        (d.note if found else d.warn)(
            f"{tool:15s} "
            + ("found" if found else "not on PATH: that check is SKIPPED and recorded per step")
        )
    s = Settings()
    if not fake:
        backends = {s.backend.value, (s.backend_b or s.backend).value}
        for b in sorted(backends):
            if b == "anthropic" or b == "agent_sdk":
                (d.note if os.environ.get("ANTHROPIC_API_KEY") else d.halt)(
                    f"{b:15s} ANTHROPIC_API_KEY "
                    + ("set" if os.environ.get("ANTHROPIC_API_KEY") else "missing")
                )
            if b == "claude_cli":
                (d.note if shutil.which("claude") else d.halt)(
                    f"{b:15s} `claude` " + ("on PATH" if shutil.which("claude") else "missing")
                )
            if b == "codex_cli":
                if shutil.which("codex"):
                    ver = subprocess.run(
                        ["codex", "--version"], capture_output=True, text=True
                    ).stdout.strip()
                    d.note(f"{b:15s} `codex` {ver}")
                else:
                    d.halt(f"{b:15s} `codex` missing")
            if b == "pydantic_ai":
                d.note(f"{b:15s} the provider's key is the model's; not probed")
    if deep:
        from . import walk

        from .recipes import registry

        rs = walk.run(registry.default_name(), only="happy")
        (d.note if rs and rs[0].ok else d.halt)(
            f"walk            {'ok' if rs and rs[0].ok else 'RED'} in {rs[0].seconds if rs else 0}s -- {rs[0].detail if rs else ''}"
        )
    if d.halts:
        print(f"doctor: halt ({len(d.halts)} halt, {len(d.warns)} warn)")
        return 2
    if d.warns:
        print(f"doctor: ok with warnings ({len(d.warns)} warn)")
        return 1
    print("doctor: ok (0 halt, 0 warn)")
    return 0
